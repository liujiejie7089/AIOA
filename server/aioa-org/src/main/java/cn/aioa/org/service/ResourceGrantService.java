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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

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
        out.put("workers", statMapper.selectWorkers());
        out.put("resTypes", List.of(
                Map.of("code", ResourceGrant.TYPE_EXPERT, "name", "专家"),
                Map.of("code", ResourceGrant.TYPE_SKILL, "name", "技能"),
                Map.of("code", ResourceGrant.TYPE_MODEL, "name", "模型"),
                Map.of("code", ResourceGrant.TYPE_KB, "name", "知识库")));
        return out;
    }

    // ================================================================== 授权管理

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
        if (!List.of(ResourceGrant.TYPE_EXPERT, ResourceGrant.TYPE_SKILL,
                ResourceGrant.TYPE_MODEL, ResourceGrant.TYPE_KB).contains(resType)) {
            throw BizException.badRequest("不支持的资源类型：" + resType);
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
        audit.record(tenantId, g.getInstitutionId(), actor, "RESOURCE_REVOKE", "RESOURCE_GRANT", id,
                "撤销机构 #" + g.getInstitutionId() + " 的 " + g.getResType() + " 授权（"
                        + (g.getResName() == null ? g.getResKey() : g.getResName()) + "）", view(g), null);
        return Map.of("revoked", id);
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> setEnabled(Long tenantId, Long id, boolean enabled, AuthUser actor) {
        ResourceGrant g = grantMapper.selectById(id);
        if (g == null || !g.getTenantId().equals(tenantId)) {
            throw BizException.notFound("授权记录不存在：" + id);
        }
        Map<String, Object> before = view(g);
        g.setEnabled(enabled);
        g.setUpdatedAt(LocalDateTime.now());
        grantMapper.updateById(g);
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
        for (String t : List.of(ResourceGrant.TYPE_EXPERT, ResourceGrant.TYPE_SKILL,
                ResourceGrant.TYPE_MODEL, ResourceGrant.TYPE_KB)) {
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
