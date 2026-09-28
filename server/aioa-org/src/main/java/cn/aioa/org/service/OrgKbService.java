package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 机构知识库（FR-I）：
 *   I1 机构知识库（按部门配置可见范围）
 *   I2 条目审核与入库留痕
 *
 * 复用既有 kb_document（V24 补齐 institution_id / department_id），
 * 不新建知识库实体，避免与用户端知识库功能重复。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrgKbService {

    private final OrgStatMapper statMapper;
    private final AuditRecorder audit;
    /** resource_grant 的 KB 账本行由 {@link ResourceGrantService} 一处维护（两条路径不可各写一份）。 */
    private final ResourceGrantService grantService;

    /** FR-I1：机构知识库清单（仅本机构）。 */
    public Map<String, Object> list(Long institutionId) {
        List<Map<String, Object>> docs = statMapper.selectKbOfInstitution(institutionId);
        long ok = docs.stream().filter(d -> "OK".equals(String.valueOf(d.get("state")))).count();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("institutionId", institutionId);
        out.put("total", docs.size());
        out.put("indexedCount", ok);
        out.put("items", docs);
        return out;
    }

    /** 可挂载的租户/个人知识库条目（企业端「从共享库引入」列表）。 */
    public List<Map<String, Object>> candidates(Long tenantId) {
        return statMapper.selectUnboundKb(tenantId);
    }

    /** FR-I1：把资料挂载到机构并配置可见范围（departmentId = 0 表示机构内全员可见）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> attach(Long tenantId, Long institutionId, AuthUser actor,
                                      Map<String, Object> body) {
        Long docId = Vals.lngObj(body, "docId");
        if (docId == null) {
            throw BizException.badRequest("docId 不能为空");
        }
        Long departmentId = Vals.lngObj(body, "departmentId");
        long deptId = departmentId == null ? 0L : departmentId;
        String scope = deptId == 0L ? "TENANT" : "DEPT";
        // 存在性单独问一次：bindKbDocument 是 UPDATE，而 MySQL 对「值未变化」的 UPDATE 返回 0 行，
        // 原先拿影响行数判「资料不存在」⇒ 把同一条资料重复挂进同一机构会被误报 404（幂等性缺陷）。
        String docName = statMapper.selectKbNameInTenant(docId, tenantId);
        if (docName == null) {
            throw BizException.notFound("知识库资料不存在或不属于本租户：" + docId);
        }
        // institution_id 是单值列：资料已属于别的机构时，继续挂载等于把它从原机构静默搬走，
        // 原机构那条授权记录随即变成幽灵行（清单说已启用、机构知识库里没有）。明确拒绝。
        Long cur = statMapper.selectKbInstitutionId(docId);
        if (cur != null && cur != 0L && !cur.equals(institutionId)) {
            throw BizException.badRequest("该知识库资料当前已被另一机构挂载，请先在那里解除挂载");
        }
        statMapper.bindKbDocument(docId, tenantId, institutionId, deptId, scope);
        // 账本同步：与资源授权页「知识库」类型走的是同一动作，两条路径必须同源（否则清单与生效态分叉）。
        grantService.syncKbLedger(tenantId, institutionId, docId, docName, true);
        audit.record(tenantId, institutionId, actor, "KB_ATTACH", "KB_DOCUMENT", docId,
                "将知识库资料 #" + docId + " 纳入机构知识库"
                        + (deptId == 0L ? "（机构内全员可见）" : "（限部门 #" + deptId + " 可见）"),
                null, Map.of("docId", docId, "departmentId", deptId, "scope", scope));
        return list(institutionId);
    }

    /** FR-I2：机构知识库条目审核（通过 → 入库可见；驳回 → 记失败原因）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> review(Long tenantId, Long institutionId, Long docId, boolean approve,
                                      String reason, AuthUser actor) {
        String state = approve ? "OK" : "FAILED";
        int n = statMapper.reviewKbDocument(docId, institutionId, state,
                approve ? null : (reason == null ? "机构审核驳回" : reason));
        if (n == 0) {
            throw BizException.notFound("知识库资料不存在或不属于本机构：" + docId);
        }
        audit.record(tenantId, institutionId, actor, approve ? "KB_REVIEW_PASS" : "KB_REVIEW_REJECT",
                "KB_DOCUMENT", docId,
                "机构知识库条目审核：" + (approve ? "通过" : "驳回")
                        + (reason == null || reason.isBlank() ? "" : "，原因：" + reason),
                null, Map.of("docId", docId, "state", state));
        return list(institutionId);
    }

    /** 解除机构挂载（资料回到租户/个人库）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> detach(Long tenantId, Long institutionId, Long docId, AuthUser actor) {
        if (statMapper.selectKbNameInTenant(docId, tenantId) == null) {
            throw BizException.notFound("知识库资料不存在或不属于本租户：" + docId);
        }
        statMapper.bindKbDocument(docId, tenantId, 0L, 0L, "TENANT");
        // 账本同步：撤掉 resource_grant 的 KB 行，否则「机构知识库已移出、授权清单仍显示已启用」。
        grantService.syncKbLedger(tenantId, institutionId, docId, null, false);
        audit.record(tenantId, institutionId, actor, "KB_DETACH", "KB_DOCUMENT", docId,
                "将知识库资料 #" + docId + " 移出机构知识库", null, Map.of("docId", docId));
        return list(institutionId);
    }
}
