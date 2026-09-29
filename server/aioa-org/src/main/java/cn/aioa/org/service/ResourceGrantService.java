package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.ResourceGrant;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.mapper.ResourceGrantMapper;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 资源按机构授权（FR-E）+ 企业端可见清单与开通申请（FR-J）。
 *
 * <p>生效规则：未授权的机构，其成员端**不可见**该资源（FR-E1）；
 * 模型清单按机构差异化并携带计费倍率（FR-E2）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ResourceGrantService implements ApprovalCallback {

    public static final String BIZ_TYPE = "RESOURCE_OPEN";

    private final ResourceGrantMapper grantMapper;
    private final OrgInstitutionMapper institutionMapper;
    private final OrgStatMapper statMapper;
    private final ApprovalFlowService flowService;
    private final AuditRecorder audit;
    private final ObjectMapper objectMapper;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    // ================================================================== 资源目录

    /** 平台可用资源目录（租户端授权页的可选项）。 */
    public Map<String, Object> catalog(Long tenantId) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("experts", statMapper.selectExperts(tenantId));
        out.put("skills", statMapper.selectSkills(tenantId));
        out.put("models", statMapper.selectModelConfigs());
        // 数字员工必须按租户过滤：此前取全表，租户 2 的授权下拉里混进了租户 3 的 4 个员工
        // （实测 11 条 = t0 3 + t2 4 + t3 4），选中即会把别家的资产授权给本租户机构，
        // 违反 docs/15 §八「tenant_id 只从 JWT 取、跨租户一律 404」。
        out.put("workers", statMapper.selectWorkers(tenantId));
        // 「知识库」的可授权目录（2026-09-28 补）。
        // 此前 catalog 没有 kb 这个键，而前端 `CAT_KEY.KB → 'kb'`、下拉读 `catalog.kb` ⇒ 恒为空数组：
        // 「资源类型选知识库 → 资源下拉空白 → 授不出去」。用户反馈的「知识库授权的问题」即此。
        out.put("kb", statMapper.selectGrantableKb(tenantId));
        // resTypes 与 grant() 的白名单同源（allTypes()），前端下拉也从这里取 —— 三处不再各写一份。
        out.put("resTypes", ResourceGrant.ALL_TYPES.stream()
                .map(code -> Map.of("code", code, "name", ResourceGrant.TYPE_NAMES.get(code)))
                .toList());
        return out;
    }

    // ================================================================== 授权管理

    /**
     * 资源授权清单（运营面口径：**已注销机构的授权不出现**）。
     *
     * <p>用户报障：「注销了机构，资源授权里还能看到它的授权」。机构注销后不再对外提供服务，
     * 其授权随机构一并失效（{@code resource_grant} 行保留，属历史留痕，不删除）。</p>
     *
     * <p>过滤放在 Java 侧而不是 JOIN 进 wrapper：{@code resource_grant} 没有指向机构状态的外键，
     * MyBatis-Plus 的 {@code LambdaQueryWrapper<ResourceGrant>} 里写不出跨表条件；
     * 先取本租户的运营面机构 id 集合再筛，语意最直白，也不会把「租户下无机构」误判成
     * {@code IN ()} 空集报错。</p>
     */
    public List<Map<String, Object>> listGrants(Long tenantId, Long institutionId, String resType) {
        LambdaQueryWrapper<ResourceGrant> w = new LambdaQueryWrapper<ResourceGrant>()
                .eq(ResourceGrant::getTenantId, tenantId);
        if (institutionId != null) {
            w.eq(ResourceGrant::getInstitutionId, institutionId);
        }
        if (resType != null && !resType.isBlank()) {
            w.eq(ResourceGrant::getResType, resType);
        }
        List<ResourceGrant> rows = grantMapper.selectList(w
                .orderByAsc(ResourceGrant::getInstitutionId)
                .orderByAsc(ResourceGrant::getResType)
                .orderByAsc(ResourceGrant::getResId));
        // 已注销机构退出运营面（判定只在一处：OrgInstitution.excludeClosed / InstitutionStatus）
        LambdaQueryWrapper<OrgInstitution> instQuery = new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId);
        OrgInstitution.excludeClosed(instQuery);
        Set<Long> liveInstitutions = new HashSet<>();
        for (OrgInstitution it : institutionMapper.selectList(instQuery)) {
            liveInstitutions.add(it.getId());
        }
        rows.removeIf(g -> !liveInstitutions.contains(g.getInstitutionId()));
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (ResourceGrant g : rows) {
            out.add(view(g));
        }
        return out;
    }

    /** FR-E1/E2：按机构授权（幂等 upsert，携带差异化参数如计费倍率）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> grant(Long tenantId, AuthUser actor, Map<String, Object> body) {
        Long institutionId = Vals.lngObj(body, "institutionId");
        if (institutionId == null) {
            throw BizException.badRequest("institutionId 不能为空");
        }
        OrgInstitution it = institutionMapper.selectById(institutionId);
        if (it == null || !tenantId.equals(it.getTenantId())) {
            throw BizException.notFound("机构不存在于本租户：" + institutionId);
        }
        String resType = Vals.require(body, "resType", "资源类型");
        // 白名单与授权目录同源（ResourceGrant.ALL_TYPES）。此前这里是硬编码的 4 类、漏了 WORKER，
        // 而管理端下拉「数字员工」能选 —— 表现为「数字员工无法授权：不支持的资源类型：WORKER」。
        if (!ResourceGrant.ALL_TYPES.contains(resType)) {
            throw BizException.badRequest("不支持的资源类型：" + resType
                    + "；可选：" + String.join("、", ResourceGrant.ALL_TYPES));
        }
        Long resId = Vals.lngObj(body, "resId");
        if (resId == null) {
            throw BizException.badRequest("resId 不能为空");
        }
        ResourceGrant g = grantMapper.selectOne(new LambdaQueryWrapper<ResourceGrant>()
                .eq(ResourceGrant::getTenantId, tenantId)
                .eq(ResourceGrant::getInstitutionId, institutionId)
                .eq(ResourceGrant::getResType, resType)
                .eq(ResourceGrant::getResId, resId)
                .last("limit 1"));
        boolean isNew = g == null;
        if (isNew) {
            g = new ResourceGrant();
            g.setTenantId(tenantId);
            g.setInstitutionId(institutionId);
            g.setResType(resType);
            g.setResId(resId);
            g.setGrantedBy(actor == null ? 0L : actor.getUserId());
            g.setGrantedAt(LocalDateTime.now());
            g.setCreatedAt(LocalDateTime.now());
        }
        g.setResKey(Vals.str(body, "resKey", g.getResKey()));
        g.setResName(Vals.str(body, "resName", g.getResName()));
        g.setExtra(Vals.str(body, "extra", g.getExtra()));
        g.setEnabled(Vals.bool(body, "enabled", true));
        g.setUpdatedAt(LocalDateTime.now());
        if (isNew) {
            grantMapper.insert(g);
        } else {
            grantMapper.updateById(g);
        }
        // 知识库：授权动作的**生效态**落在 kb_document.institution_id（机构知识库），不另立一套判定。
        // resource_grant 的 KB 行是同一动作的账本镜像，两条路径（/tenant/grants 与 /org/kb）
        // 都经 {@link #syncKbLedger} 维护，避免「清单说启用了、机构知识库里却没有」。
        if (ResourceGrant.TYPE_KB.equals(resType)) {
            applyKbBinding(tenantId, institutionId, resId, Boolean.TRUE.equals(g.getEnabled()));
        }
        audit.record(tenantId, institutionId, actor,
                isNew ? "RESOURCE_GRANT" : "RESOURCE_GRANT_UPDATE", "RESOURCE_GRANT", g.getId(),
                (isNew ? "授权" : "更新授权") + "「" + resType + " / "
                        + (g.getResName() == null ? g.getResKey() : g.getResName())
                        + "」给机构「" + it.getName() + "」"
                        + (g.getExtra() == null ? "" : "，参数 " + g.getExtra()), null, view(g));
        return view(g);
    }

    /** 批量授权（一次给某机构开多个资源）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> batchGrant(Long tenantId, AuthUser actor, Map<String, Object> body) {
        List<Map<String, Object>> items = Vals.list(body, "items");
        if (items.isEmpty()) {
            throw BizException.badRequest("items 不能为空");
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> item : items) {
            Map<String, Object> merged = new LinkedHashMap<>(body);
            merged.remove("items");
            merged.putAll(item);
            out.add(grant(tenantId, actor, merged));
        }
        return Map.of("granted", out.size(), "items", out);
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> revoke(Long tenantId, Long id, AuthUser actor) {
        ResourceGrant g = grantMapper.selectById(id);
        if (g == null || !g.getTenantId().equals(tenantId)) {
            throw BizException.notFound("授权记录不存在：" + id);
        }
        grantMapper.deleteById(id);
        // 知识库：撤销授权 = 解挂（资料回到租户共享库），否则「清单已删、机构知识库里还在」。
        if (ResourceGrant.TYPE_KB.equals(g.getResType())) {
            statMapper.bindKbDocument(g.getResId(), tenantId, 0L, 0L, "TENANT");
        }
        audit.record(tenantId, g.getInstitutionId(), actor, "RESOURCE_REVOKE", "RESOURCE_GRANT", id,
                "撤销机构 #" + g.getInstitutionId() + " 的 " + g.getResType() + " 授权（"
                        + (g.getResName() == null ? g.getResKey() : g.getResName()) + "）", view(g), null);
        return Map.of("revoked", id);
    }

    /**
     * 启用 / 停用资源授权。
     *
     * @param explicit 期望的目标状态；传 {@code null} 表示「按当前值翻转」
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> setEnabled(Long tenantId, Long id, Boolean explicit, AuthUser actor) {
        ResourceGrant g = grantMapper.selectById(id);
        if (g == null || !g.getTenantId().equals(tenantId)) {
            throw BizException.notFound("授权记录不存在：" + id);
        }
        // 不传目标值时真翻转。**绝不能默认成 true** —— 调用方不带 body 时那会把
        // 「停用」静默变成「启用」，记录始终是已启用（实测缺陷「停用操作无效」）。
        boolean enabled = explicit != null ? explicit : !Boolean.TRUE.equals(g.getEnabled());
        Map<String, Object> before = view(g);
        g.setEnabled(enabled);
        g.setUpdatedAt(LocalDateTime.now());
        grantMapper.updateById(g);
        // 知识库：停用 = 从机构知识库移出，启用 = 挂回该机构（生效态只有 kb_document 一处）。
        if (ResourceGrant.TYPE_KB.equals(g.getResType())) {
            applyKbBinding(tenantId, g.getInstitutionId(), g.getResId(), enabled);
        }
        audit.record(tenantId, g.getInstitutionId(), actor, "RESOURCE_GRANT_TOGGLE", "RESOURCE_GRANT", id,
                (enabled ? "启用" : "停用") + "机构 #" + g.getInstitutionId() + " 的资源授权", before, view(g));
        return view(g);
    }

    // ================================================================== FR-J 企业端

    /** FR-J1：本机构已授权且启用的资源清单（成员端可见的唯一来源）。 */
    public Map<String, Object> institutionResources(Long tenantId, Long institutionId) {
        List<ResourceGrant> rows = grantMapper.selectList(new LambdaQueryWrapper<ResourceGrant>()
                .eq(ResourceGrant::getTenantId, tenantId)
                .eq(ResourceGrant::getInstitutionId, institutionId)
                .eq(ResourceGrant::getEnabled, true)
                .orderByAsc(ResourceGrant::getResType)
                .orderByAsc(ResourceGrant::getResId));
        Map<String, List<Map<String, Object>>> byType = new LinkedHashMap<>();
        // 预置空分组用同一个权威清单：此前只预置 4 类，数字员工即使授权成功也不会出现在
        // byType 里（前端按固定 key 取数时会显示为空，等于「授权了但看不见」）。
        for (String t : ResourceGrant.ALL_TYPES) {
            byType.put(t, new ArrayList<>());
        }
        for (ResourceGrant g : rows) {
            byType.computeIfAbsent(g.getResType(), k -> new ArrayList<>()).add(view(g));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("institutionId", institutionId);
        out.put("total", rows.size());
        out.put("byType", byType);
        out.put("items", rows.stream().map(this::view).toList());
        return out;
    }

    /** FR-J2：企业管理员向租户申请开通未授权资源（走多级审批，通过后自动授权）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> submitOpenApplication(Long tenantId, Long institutionId, AuthUser actor,
                                                     Map<String, Object> body) {
        String resType = Vals.require(body, "resType", "资源类型");
        Long resId = Vals.lngObj(body, "resId");
        if (resId == null) {
            throw BizException.badRequest("resId 不能为空");
        }
        ResourceGrant exists = grantMapper.selectOne(new LambdaQueryWrapper<ResourceGrant>()
                .eq(ResourceGrant::getTenantId, tenantId)
                .eq(ResourceGrant::getInstitutionId, institutionId)
                .eq(ResourceGrant::getResType, resType)
                .eq(ResourceGrant::getResId, resId)
                .eq(ResourceGrant::getEnabled, true)
                .last("limit 1"));
        if (exists != null) {
            throw BizException.badRequest("该资源已授权，无需申请");
        }
        String resName = Vals.str(body, "resName", "资源 #" + resId);
        String formData = toJson(Map.of(
                "resType", resType,
                "resId", resId,
                "resKey", Vals.str(body, "resKey", ""),
                "resName", resName,
                "reason", Vals.str(body, "reason", "")));
        Map<String, Object> flow = flowService.submit(tenantId, actor,
                new ApprovalFlowService.SubmitReq(BIZ_TYPE,
                        "资源开通申请：" + resName,
                        Vals.str(body, "reason", "企业端申请开通未授权资源"),
                        formData, institutionId, null, null, actor.getUserId(),
                        AuditRecorder.displayName(actor), null, null, null));
        return flow;
    }

    // ================================================================== 审批回调

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onApproved(Map<String, Object> order) {
        String formData = order.get("formData") == null ? null : String.valueOf(order.get("formData"));
        if (formData == null || formData.isBlank() || "null".equals(formData)) {
            return;
        }
        try {
            Map<String, Object> f = objectMapper.readValue(formData, Map.class);
            Long tenantId = ((Number) order.get("tenantId")).longValue();
            Long institutionId = resolveInstitution(order);
            Object resType = f.get("resType");
            Object resId = f.get("resId");
            if (resType == null || resId == null) {
                return;
            }
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("institutionId", institutionId);
            body.put("resType", String.valueOf(resType));
            body.put("resId", Long.parseLong(String.valueOf(resId)));
            body.put("resKey", f.get("resKey"));
            body.put("resName", f.get("resName"));
            body.put("enabled", true);
            body.put("extra", objectMapper.writeValueAsString(
                    Map.of("source", "RESOURCE_OPEN_APPROVED", "orderId", order.get("id"))));
            grant(tenantId, null, body);
            log.info("resource opened by approval: orderId={} institutionId={} resType={} resId={}",
                    order.get("id"), institutionId, resType, resId);
        } catch (Exception e) {
            log.error("open resource failed on approval: orderId={}", order.get("id"), e);
        }
    }

    @Override
    public void onRejected(Map<String, Object> order) {
        log.info("resource open rejected: orderId={}", order.get("id"));
    }

    private Long resolveInstitution(Map<String, Object> order) {
        // approval_order 未直接存 institution_id，从 formData 场景可知来自企业端，
        // 这里以「机构管理员所属机构」为准：退回申请人的机构
        Object uid = order.get("userId");
        if (uid instanceof Number n) {
            List<OrgInstitution> list = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                    .eq(OrgInstitution::getAdminUserId, n.longValue())
                    .orderByAsc(OrgInstitution::getId)
                    .last("limit 1"));
            if (!list.isEmpty()) {
                return list.get(0).getId();
            }
        }
        throw BizException.badRequest("无法确定资源开通申请的机构归属");
    }

    // ================================================================== 知识库（KB）授权的生效态同步

    /**
     * 知识库授权的**生效动作**：把资料挂到机构 / 移回租户共享库。
     *
     * <p>生效态的唯一来源是 {@code kb_document.institution_id}（用户端机构知识库、机构/部门统计
     * 都读它）。资源授权页因此**不新造第二套可见性判定** —— 接通时选择的是「授权 = 挂载」这条同源路线。</p>
     */
    void applyKbBinding(Long tenantId, Long institutionId, Long docId, boolean bound) {
        if (bound && statMapper.selectKbNameInTenant(docId, tenantId) == null) {
            throw BizException.notFound("知识库资料不存在或不属于本租户：" + docId);
        }
        Long current = statMapper.selectKbInstitutionId(docId);
        if (bound && current != null && current != 0L && !current.equals(institutionId)) {
            // 资料已属于别的机构。`institution_id` 单值 ⇒ 继续执行等于**把它从原机构搬走**，
            // 而原机构那条授权记录会变成幽灵行。宁可明确拒绝，也不静默搬走（铁律 #2）。
            // 文案不点出对方机构 id：跨租户时那属于「泄露存在性」。
            throw BizException.badRequest("该知识库资料当前已被另一机构挂载，请先在那里解除授权后再授权到本机构");
        }
        // 幂等：MySQL 对「SET 值与现值相同」的 UPDATE 返回 0 行，故存在性判据必须单独问（见上），
        // 不能拿影响行数当「不存在」的证据。
        statMapper.bindKbDocument(docId, tenantId, bound ? institutionId : 0L, 0L, "TENANT");
    }

    /**
     * 机构知识库挂载 / 解挂的**账本同步**（由 {@link OrgKbService} 在 attach/detach 后调用）。
     *
     * <p>{@code resource_grant} 的 KB 行是「机构知识库挂载」这一动作的账本镜像。写入规则只在本类
     * 实现一处：若两条路径（{@code /tenant/grants} 与 {@code /org/kb}）各自写一份，清单与实际生效态
     * 必然分叉 —— 正是本项目反复出现的那类缺陷（docs/37 §6）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public void syncKbLedger(Long tenantId, Long institutionId, Long docId, String docName, boolean bound) {
        LambdaQueryWrapper<ResourceGrant> w = new LambdaQueryWrapper<ResourceGrant>()
                .eq(ResourceGrant::getTenantId, tenantId)
                .eq(ResourceGrant::getInstitutionId, institutionId)
                .eq(ResourceGrant::getResType, ResourceGrant.TYPE_KB)
                .eq(ResourceGrant::getResId, docId);
        if (!bound) {
            grantMapper.delete(w);
            return;
        }
        ResourceGrant g = grantMapper.selectOne(w.last("limit 1"));
        boolean isNew = g == null;
        if (isNew) {
            g = new ResourceGrant();
            g.setTenantId(tenantId);
            g.setInstitutionId(institutionId);
            g.setResType(ResourceGrant.TYPE_KB);
            g.setResId(docId);
            g.setGrantedBy(0L);
            g.setGrantedAt(LocalDateTime.now());
            g.setCreatedAt(LocalDateTime.now());
        }
        g.setResName(docName);
        g.setEnabled(true);
        g.setUpdatedAt(LocalDateTime.now());
        if (isNew) {
            grantMapper.insert(g);
        } else {
            grantMapper.updateById(g);
        }
    }

    // ------------------------------------------------------------------ 工具

    private Map<String, Object> view(ResourceGrant g) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", g.getId());
        m.put("tenantId", g.getTenantId());
        m.put("institutionId", g.getInstitutionId());
        m.put("resType", g.getResType());
        m.put("resId", g.getResId());
        m.put("resKey", g.getResKey());
        m.put("resName", g.getResName());
        m.put("extra", g.getExtra());
        m.put("enabled", g.getEnabled());
        m.put("grantedBy", g.getGrantedBy());
        m.put("grantedAt", g.getGrantedAt() == null ? null : g.getGrantedAt().toString());
        OrgInstitution it = institutionMapper.selectById(g.getInstitutionId());
        m.put("institutionName", it == null ? null : it.getName());
        return m;
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            throw BizException.badRequest("序列化失败：" + e.getMessage());
        }
    }
}
