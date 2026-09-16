package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.mapper.OrgInstitutionMapper;
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

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * FR-H3 额度扩容申请（企业管理员 → 租户管理员）演示链路。
 *
 * <p>审批通过后自动为机构配额加额并解冻（见 {@link #onApproved}），
 * 兑现入驻闭环「第 7 步额度不足 → 申请 → 第 8 步处理」的贯通。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QuotaExpandService implements ApprovalCallback {

    public static final String BIZ_TYPE = "QUOTA_EXPAND";

    private final QuotaService quotaService;
    private final OrgInstitutionMapper institutionMapper;
    private final ApprovalFlowService flowService;
    private final ObjectMapper objectMapper;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    /** 企业管理员提交扩容申请。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> submit(Long tenantId, Long institutionId, AuthUser actor,
                                     Map<String, Object> body) {
        long tokens = Vals.lng(body, "tokens", 0L);
        if (tokens <= 0) {
            throw BizException.badRequest("申请扩容词元数必须大于 0");
        }
        if (tokens > 100_000_000L) {
            throw BizException.badRequest("单次扩容申请不得超过 1 亿词元");
        }
        OrgInstitution it = institutionMapper.selectById(institutionId);
        if (it == null) {
            throw BizException.notFound("机构不存在：" + institutionId);
        }
        String reason = Vals.str(body, "reason");
        String formData = toJson(Map.of(
                "tokens", tokens,
                "institutionId", institutionId,
                "reason", reason == null ? "" : reason));
        Map<String, Object> flow = flowService.submit(tenantId, actor,
                new ApprovalFlowService.SubmitReq(BIZ_TYPE,
                        "额度扩容申请：" + it.getName() + " 申请增加 " + tokens + " 词元",
                        Vals.str(body, "reason", "机构配额不足，申请扩容"),
                        formData, institutionId, null, null, actor.getUserId(),
                        AuditRecorder.displayName(actor), null, null, null));
        return flow;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onApproved(Map<String, Object> order) {
        try {
            Long tenantId = ((Number) order.get("tenantId")).longValue();
            Long institutionId = resolveInstitution(order);
            long tokens = extractTokens(order);
            if (tokens <= 0) {
                log.warn("quota expand approved but tokens missing: orderId={}", order.get("id"));
                return;
            }
            Map<String, Object> result = quotaService.applyOrgQuotaDelta(
                    tenantId, institutionId, tokens,
                    "FR-H3 扩容申请审批通过（审批单 #" + order.get("id") + "）", null);
            log.info("quota expanded: orderId={} institutionId={} +{} -> {}",
                    order.get("id"), institutionId, tokens, result.get("quotaTokens"));
        } catch (Exception e) {
            log.error("quota expand failed on approval: orderId={}", order.get("id"), e);
            throw e;
        }
    }

    @Override
    public void onRejected(Map<String, Object> order) {
        log.info("quota expand rejected: orderId={}", order.get("id"));
    }

    private long extractTokens(Map<String, Object> order) {
        String formData = order.get("formData") == null ? null : String.valueOf(order.get("formData"));
        if (formData == null || formData.isBlank() || "null".equals(formData)) {
            return 0L;
        }
        try {
            Map<?, ?> f = objectMapper.readValue(formData, Map.class);
            Object v = f.get("tokens");
            return v == null ? 0L : Long.parseLong(String.valueOf(v).split("\\.")[0]);
        } catch (Exception e) {
            log.warn("parse expand formData failed: {}", e.getMessage());
            return 0L;
        }
    }

    private Long resolveInstitution(Map<String, Object> order) {
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
        throw BizException.badRequest("无法确定扩容申请的机构归属");
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            throw BizException.badRequest("序列化失败：" + e.getMessage());
        }
    }

    /** 申请单列表（企业端「我的申请」用）。 */
    public Map<String, Object> view(Map<String, Object> flow) {
        Map<String, Object> m = new LinkedHashMap<>(flow);
        m.put("bizType", BIZ_TYPE);
        return m;
    }
}
