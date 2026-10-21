package cn.aios.resource.service;

import cn.aios.common.exception.BizException;
import cn.aios.common.port.ApprovalOutcomeSink;
import cn.aios.org.service.ApprovalFlowService;
import cn.aios.resource.entity.FormSubmission;
import cn.aios.resource.entity.FormTemplate;
import cn.aios.resource.mapper.FormSubmissionMapper;
import cn.aios.resource.service.FormRuleException;
import cn.aios.resource.service.FormSchemaValidator.FieldError;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 表单提交与数据流转服务（docs/52 P4）。
 *
 * <p>流程：取定义 → 后端权威校验 → 落 form_submission → 按 submit_policy 分流
 * （LEDGER 落台账 / APPROVAL 走审批 / RESUME 标回填）→ 渲染回执。
 * 终态失败（如 APPROVAL 调用异常）必须回写 FAILED 并向上抛，不能静默成功。</p>
 */
@Service
@RequiredArgsConstructor
public class FormSubmissionService implements ApprovalOutcomeSink {

    private static final Logger log = LoggerFactory.getLogger(FormSubmissionService.class);

    private final FormTemplateService templateService;
    private final FormSubmissionMapper submissionMapper;
    private final ApprovalFlowService approvalFlowService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 提交结果。 */
    public record SubmitResult(Long submissionId, String status, boolean resume,
                               Long approvalOrderId, Map<String, Object> receipt) {
    }

    /** 提交返回正文：{data:{...}, conversationId?, runId?}。 */
    public record SubmitBody(Map<String, Object> data, Long conversationId, String runId) {
    }

    /**
     * 提交一份表单。
     *
     * @param tenantId     租户
     * @param applicantId  提交人
     * @param code         表单码
     * @param data         用户填写数据
     * @param conversationId 来源会话（对话内提交，可空）
     * @param runId        来源 run（对话内提交，可空）
     */
    public SubmitResult submit(Long tenantId, Long applicantId, String code,
                              Map<String, Object> data, Long conversationId, String runId) {
        if (data == null) {
            data = Map.of();
        }
        // ① 取定义（不存在/非 ACTIVE 抛中文异常）
        FormTemplate template = templateService.getByCode(tenantId, code);
        if (template == null) {
            throw BizException.notFound("表单不存在或未启用：" + code);
        }
        // ② 后端权威校验（失败抛带字段错误的中文异常）
        List<FieldError> errors = FormSchemaValidator.validate(template.getSchemaJson(), data);
        if (!errors.isEmpty()) {
            // 校验器的 message 里已经带了**字段中文名**（FormFieldMeta.label → title），
            // 这里不再前置英文键名：否则用户看到「today_work：必填字段「今日工作」不能为空」，
            // 一眼全是技术噪音（2026-10-17 实测）。字段键仍保留在 FieldError.field 供机器用。
            String detail = errors.stream()
                    .map(FieldError::message)
                    .collect(Collectors.joining("；"));
            throw BizException.badRequest("表单校验未通过：" + detail);
        }
        // ②.5 业务规则强分支校验：条件成立即拦截（如「病假必须附诊断证明」），
        // 命中的规则交给 FormRuleExceptionHandler 转成 HTTP 200 + code=40090 返回前端。
        List<FormSchemaValidator.RuleHit> ruleHits =
                FormSchemaValidator.validateRules(template.getSchemaJson(), data);
        if (!ruleHits.isEmpty()) {
            throw new FormRuleException(ruleHits);
        }
        // ②.6 落库前按 schema 白名单裁剪：丢弃 schema 未定义的脏 key，避免一路进库
        // （含 approval_order.form_data 快照）。allowed 一定非空——前面 validate 已保证 schema 合法。
        Set<String> allowed = FormSchemaValidator.propertyNames(template.getSchemaJson());
        Map<String, Object> cleaned = new LinkedHashMap<>();
        List<String> dropped = new ArrayList<>();
        data.forEach((k, v) -> {
            if (allowed.contains(k)) {
                cleaned.put(k, v);
            } else {
                dropped.add(k);
            }
        });
        if (!dropped.isEmpty()) {
            log.warn("表单提交含未定义字段，已丢弃：code={} fields={}", code, dropped);
        }
        data = cleaned;
        // ③ 落 form_submission（status 初始 SUBMITTED，data_json 落白名单裁剪后的 cleaned）
        FormSubmission sub = new FormSubmission();
        sub.setTenantId(tenantId);
        sub.setTemplateId(template.getId());
        sub.setTemplateVersion(template.getVersion());
        sub.setCode(template.getCode());
        sub.setBizType(template.getBizType());
        sub.setApplicantId(applicantId);
        try {
            sub.setDataJson(objectMapper.writeValueAsString(data));
        } catch (Exception e) {
            throw BizException.badRequest("表单数据序列化失败");
        }
        sub.setStatus(FormSubmission.STATUS_SUBMITTED);
        sub.setConversationId(conversationId);
        sub.setRunId(runId);
        sub.setSubmittedAt(LocalDateTime.now());
        sub.setUpdatedAt(LocalDateTime.now());
        submissionMapper.insert(sub);

        // ④ 按 submit_policy 分流
        List<String> policies = parsePolicy(template.getSubmitPolicy());
        boolean resume = policies.contains(FormTemplate.POLICY_RESUME);
        Long approvalOrderId = null;

        if (policies.contains(FormTemplate.POLICY_APPROVAL)) {
            try {
                approvalOrderId = invokeApproval(tenantId, applicantId, template, sub.getId(), data);
                sub.setStatus(FormSubmission.STATUS_APPROVING);
                sub.setApprovalOrderId(approvalOrderId);
            } catch (Exception e) {
                // 终态失败必须回写，并向上抛（不静默成功）
                sub.setStatus(FormSubmission.STATUS_FAILED);
                sub.setUpdatedAt(LocalDateTime.now());
                submissionMapper.updateById(sub);
                throw BizException.badRequest("提交审批失败：" + e.getMessage());
            }
        } else if (policies.contains(FormTemplate.POLICY_LEDGER)) {
            sub.setStatus(FormSubmission.STATUS_DONE);
        }
        // 仅 RESUME（或空策略）时状态保持 SUBMITTED，由调用方回填对话
        sub.setUpdatedAt(LocalDateTime.now());
        submissionMapper.updateById(sub);

        // ⑤ 渲染回执
        Map<String, Object> receipt = renderReceipt(template, sub.getId(), data);
        // 回执透出 submissionId / status，供前端 formReceiptHtml 显示受理单号与当前状态
        // （前端按 receipt.submissionId / receipt.status 取值，否则恒显示「—」）。
        receipt.put("submissionId", sub.getId());
        receipt.put("status", sub.getStatus());
        receipt.put("statusLabel", statusLabel(sub.getStatus()));
        return new SubmitResult(sub.getId(), sub.getStatus(), resume, approvalOrderId, receipt);
    }

    /** 调审批引擎：把 submission 快照（含 submissionId 与用户数据）作为 formData 传入。 */
    private Long invokeApproval(Long tenantId, Long applicantId, FormTemplate template,
                               Long submissionId, Map<String, Object> data) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("submissionId", submissionId);
        snapshot.put("data", data);
        String formData;
        try {
            formData = objectMapper.writeValueAsString(snapshot);
        } catch (Exception e) {
            throw BizException.badRequest("审批快照序列化失败");
        }
        AuthUser actor = AuthUserContext.require();
        Long institutionId = actor.getInstitutionId() != null ? actor.getInstitutionId() : 0L;
        Map<String, Object> out = approvalFlowService.submit(tenantId, actor,
                new ApprovalFlowService.SubmitReq(
                        template.getBizType(),   // bizType
                        template.getName(),       // title
                        "表单提交：" + template.getName(), // content
                        formData,                 // formData
                        institutionId,            // institutionId
                        null,                     // departmentId
                        null,                     // days
                        applicantId,              // applicantUserId
                        null,                     // applicantName（由引擎按 actor 兜底）
                        null,                     // specificApproverId
                        null,                     // applicantType
                        null));                   // applicantDepartmentId
        Object orderId = out.get("orderId");
        if (orderId == null) {
            throw BizException.badRequest("审批单创建失败");
        }
        return ((Number) orderId).longValue();
    }

    /**
     * 提交记录列表。
     *
     * <p>「按申请人过滤」的判定只在此一处：管理员（持有 form:manage）看全租户，普通成员只看自己。
     * {@code applicantId} 为 null 表示不按申请人过滤（管理员全租户视图）。</p>
     */
    public IPage<FormSubmission> list(Long tenantId, Long applicantId, boolean admin,
                                     String code, String status, int page, int size) {
        LambdaQueryWrapper<FormSubmission> w = new LambdaQueryWrapper<FormSubmission>()
                .eq(FormSubmission::getTenantId, tenantId)
                .orderByDesc(FormSubmission::getId);
        if (!admin && applicantId != null) {
            w.eq(FormSubmission::getApplicantId, applicantId);
        }
        if (code != null && !code.isBlank()) {
            w.eq(FormSubmission::getCode, code);
        }
        if (status != null && !status.isBlank()) {
            w.eq(FormSubmission::getStatus, status);
        }
        return submissionMapper.selectPage(new Page<>(Math.max(page, 1), Math.max(size, 1)), w);
    }

    /**
     * 渲染回执：按 receipt_json 把字段值套入；缺失时用「表单名 + 提交成功 + 单号」兜底。
     *
     * <p>receipt_json 结构：{ "title":"...", "lines":[{"label":"...","value":"${field}"}] }，
     * value 中的 {@code ${field}} 用 data 对应字段替换。</p>
     */
    private Map<String, Object> renderReceipt(FormTemplate template, Long submissionId,
                                             Map<String, Object> data) {
        String receiptJson = template.getReceiptJson();
        if (receiptJson != null && !receiptJson.isBlank()) {
            try {
                @SuppressWarnings("unchecked")
                Map<String, Object> receipt = objectMapper.readValue(receiptJson,
                        new TypeReference<LinkedHashMap<String, Object>>() {
                        });
                Object titleObj = receipt.get("title");
                String title = titleObj == null ? null : titleObj.toString();
                Object linesObj = receipt.get("lines");
                List<Map<String, Object>> lines = new ArrayList<>();
                if (linesObj instanceof List<?> rawLines) {
                    for (Object lo : rawLines) {
                        if (!(lo instanceof Map<?, ?> lm)) {
                            continue;
                        }
                        @SuppressWarnings("unchecked")
                        Map<String, Object> lineSrc = (Map<String, Object>) lm;
                        String label = lineSrc.get("label") == null ? "" : lineSrc.get("label").toString();
                        String valueTpl = lineSrc.get("value") == null ? "" : lineSrc.get("value").toString();
                        String value = substitute(valueTpl, data);
                        if (value == null) {
                            // 关键字段缺失：兜底，不返回半成品回执
                            log.warn("回执引用了未填字段，已退化兜底：code={} submissionId={} field={}",
                                    template.getCode(), submissionId, valueTpl);
                            return fallbackReceipt(template, submissionId);
                        }
                        Map<String, Object> line = new LinkedHashMap<>();
                        line.put("label", label);
                        line.put("value", value);
                        lines.add(line);
                    }
                }
                if (title == null || title.isBlank() || lines.isEmpty()) {
                    // 配置存在但不可用：必须留痕，否则「配了回执但全是兜底」长期无人发现
                    // （2026-10-17 实测：43 张表单的 receipt_json 写的是 display_fields，
                    // 与这里的 lines 契约不符，静默兜底了整整一轮迭代）。
                    log.warn("回执配置缺 title/lines，已退化兜底：code={} submissionId={}",
                            template.getCode(), submissionId);
                    return fallbackReceipt(template, submissionId);
                }
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("title", title);
                out.put("lines", lines);
                return out;
            } catch (Exception e) {
                log.warn("回执配置解析失败，已退化兜底：code={} submissionId={} err={}",
                        template.getCode(), submissionId, e.getMessage());
                return fallbackReceipt(template, submissionId);
            }
        }
        return fallbackReceipt(template, submissionId);
    }

    /** 提交状态中文展示（回执 statusLabel 用）。未知状态原样回退，避免遮蔽端上兜底。 */
    private String statusLabel(String status) {
        if (status == null) {
            return "已提交";
        }
        return switch (status) {
            case FormSubmission.STATUS_SUBMITTED -> "已提交";
            case FormSubmission.STATUS_APPROVING -> "审批中";
            case FormSubmission.STATUS_APPROVED -> "审批通过";
            case FormSubmission.STATUS_REJECTED -> "审批驳回";
            case FormSubmission.STATUS_DONE -> "已完成";
            case FormSubmission.STATUS_CANCELED -> "已撤销";
            case FormSubmission.STATUS_FAILED -> "提交失败";
            default -> status;
        };
    }

    private Map<String, Object> fallbackReceipt(FormTemplate template, Long submissionId) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("title", template.getName() + "提交成功");
        List<Map<String, Object>> lines = new ArrayList<>();
        Map<String, Object> line = new LinkedHashMap<>();
        line.put("label", "提交单号");
        line.put("value", String.valueOf(submissionId));
        lines.add(line);
        out.put("lines", lines);
        return out;
    }

    /** 把模板串里的 ${field} 用 data 替换；非 ${...} 原样返回；引用字段缺失返回 null。 */
    private String substitute(String tpl, Map<String, Object> data) {
        if (tpl == null) {
            return null;
        }
        if (!tpl.contains("${")) {
            return tpl;
        }
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("\\$\\{([^}]+)}")
                .matcher(tpl);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            String key = m.group(1);
            Object v = data == null ? null : data.get(key);
            if (v == null) {
                return null; // 关键字段缺失：交给调用方兜底
            }
            m.appendReplacement(sb, java.util.regex.Matcher.quoteReplacement(v.toString()));
        }
        m.appendTail(sb);
        return sb.toString();
    }

    private List<String> parsePolicy(String policy) {
        if (policy == null || policy.isBlank()) {
            return List.of(FormTemplate.POLICY_LEDGER);
        }
        List<String> out = new ArrayList<>();
        for (String p : policy.split("\\+")) {
            String t = p.trim().toUpperCase();
            if (!t.isEmpty()) {
                out.add(t);
            }
        }
        return out.isEmpty() ? List.of(FormTemplate.POLICY_LEDGER) : out;
    }

    // ================================================================== 审批终态回写（docs/52 P4 铁律 2）

    /**
     * 审批终态回调：把 {@code form_submission} 落成与审批单一致的终态（APPROVED/REJECTED）。
     *
     * <p>实现 {@link ApprovalOutcomeSink}，由审批引擎在审批单进入终态时（唯一回调点
     * {@code ApprovalFlowService#fire}）调用，且同处 {@code decide} 的 {@code @Transactional}
     * 事务内 —— 二者同事务提交或同事务回滚，绝不会「审批已终态但 submission 仍 APPROVING」。</p>
     *
     * <ul>
     *   <li>按 {@code approval_order_id} 查活行（未逻辑删除）；查不到只记 warn 返回 ——
     *       历史审批单据没有对应表单属正常情况，不得抛异常。</li>
     *   <li>幂等：本单据已是任意终态时重复回调不报错、不改写。</li>
     *   <li>未知决策类型（非 APPROVED/REJECTED）只记 warn 返回，不误写。</li>
     * </ul>
     */
    @Override
    public void onApprovalFinished(Long approvalOrderId, String decision) {
        if (approvalOrderId == null) {
            log.warn("审批终态回调：approvalOrderId 为空，跳过");
            return;
        }
        FormSubmission sub = submissionMapper.selectOne(new LambdaQueryWrapper<FormSubmission>()
                .eq(FormSubmission::getApprovalOrderId, approvalOrderId)
                .isNull(FormSubmission::getDeletedAt));
        if (sub == null) {
            // 历史审批单据没有对应表单是正常的（并非每笔审批都来自表单提交），只记 warn 返回。
            log.warn("审批终态回调：未找到关联 form_submission（可能为非表单审批），审批单={}，决策={}",
                    approvalOrderId, decision);
            return;
        }
        String target;
        if (FormSubmission.STATUS_APPROVED.equals(decision)) {
            target = FormSubmission.STATUS_APPROVED;
        } else if (FormSubmission.STATUS_REJECTED.equals(decision)) {
            target = FormSubmission.STATUS_REJECTED;
        } else {
            log.warn("审批终态回调：未知决策类型，审批单={}，决策={}", approvalOrderId, decision);
            return;
        }
        // 幂等：已经是任意终态则不再改写（避免重复终态回调覆盖或翻账）。
        if (isTerminal(sub.getStatus())) {
            log.info("审批终态回调：submission 已为终态，幂等跳过，id={}，状态={}，决策={}",
                    sub.getId(), sub.getStatus(), decision);
            return;
        }
        sub.setStatus(target);
        sub.setUpdatedAt(LocalDateTime.now());
        submissionMapper.updateById(sub);
        log.info("审批终态回写 form_submission：id={}，审批单={}，状态={}", sub.getId(), approvalOrderId, target);
    }

    /** 是否终态：APPROVED/REJECTED/DONE/CANCELED/FAILED 均视为终态，终态不再被回调改写。 */
    private static boolean isTerminal(String status) {
        return FormSubmission.STATUS_APPROVED.equals(status)
                || FormSubmission.STATUS_REJECTED.equals(status)
                || FormSubmission.STATUS_DONE.equals(status)
                || FormSubmission.STATUS_CANCELED.equals(status)
                || FormSubmission.STATUS_FAILED.equals(status);
    }
}
