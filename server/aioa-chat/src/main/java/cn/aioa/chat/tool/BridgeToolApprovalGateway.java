package cn.aioa.chat.tool;

import cn.aioa.bridge.support.ToolApprovalGateway;
import cn.aioa.org.service.ApprovalFlowService;
import cn.aioa.security.AuthUser;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 工具调用审批网关的实现（{@code aioa-bridge} 侧只留了接口）。
 *
 * <p>落在这里的原因和 {@code PermissionGrantToolHandler} 一样：一次「高风险工具调用」
 * 同时属于<b>工具域</b>（谁来调、调什么）与<b>审批域</b>（谁批、几级），
 * 而 {@code aioa-bridge} 与 {@code aioa-org} 是兄弟模块、互不依赖。
 * 本模块是唯一同时看得见两者的地方，因此由它把接口接通 —— 桥接与审批引擎都不必知道对方存在。</p>
 *
 * <p><b>业务类型 {@code TOOL_INVOKE}</b> 不预置流程定义：审批引擎在找不到定义时
 * 会落到「内置单级兜底」（企业管理员），语义正好是「高风险工具由机构管理员把关」。
 * 需要多级时，管理端按 {@code TOOL_INVOKE} 配一张流程定义即可，本类不必改。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class BridgeToolApprovalGateway implements ToolApprovalGateway {

    /** 工具调用审批的业务类型（可被管理端流程配置引用）。 */
    public static final String BIZ_TYPE = "TOOL_INVOKE";

    private final ApprovalFlowService approvalFlowService;
    private final ObjectMapper objectMapper;

    @Override
    public Long submit(ApprovalRequest request) {
        AuthUser applicant = request.applicant();
        long tenantId = request.tenantId() == null ? 0L : request.tenantId();
        Long institutionId = applicant == null ? null : applicant.getInstitutionId();
        Long departmentId = applicant == null ? null : applicant.getDepartmentId();
        String applicantName = applicant == null ? null
                : (applicant.getNickname() != null ? applicant.getNickname() : applicant.getUsername());

        ApprovalFlowService.SubmitReq req = new ApprovalFlowService.SubmitReq(
                BIZ_TYPE,
                request.title(),
                buildContent(request),
                buildFormData(request),
                institutionId,
                departmentId,
                null,
                applicant == null ? null : applicant.getUserId(),
                applicantName,
                null,
                null,
                null);
        Map<String, Object> out = approvalFlowService.submit(tenantId, applicant, req);
        Object orderId = out == null ? null : out.get("orderId");
        if (orderId == null) {
            log.warn("工具调用审批提交未返回 orderId：tool={}, logId={}",
                    request.toolCode(), request.invocationLogId());
            return null;
        }
        Long id = ((Number) orderId).longValue();
        log.info("工具调用已进入审批：tool={}, orderId={}, 申请人={}",
                request.toolCode(), id, applicantName);
        return id;
    }

    /** 审批单正文：写清「调哪个工具、第几版、挂起日志 id」，便于审批人追溯。 */
    private String buildContent(ApprovalRequest request) {
        return "AI 助手请求调用工具「" + request.toolCode() + "」（版本 "
                + (request.version() == null ? "默认" : request.version()) + "）。\n"
                + "该工具被标记为需审批（tool_definition.requires_approval=1），"
                + "调用已在桥接层挂起（日志 #" + request.invocationLogId() + "），"
                + "审批通过后自动执行，无需申请人再次发起。\n"
                + "调用参数：" + toJson(request.args());
    }

    private String buildFormData(ApprovalRequest request) {
        Map<String, Object> form = new LinkedHashMap<>();
        form.put("kind", "TOOL_INVOKE");
        form.put("toolCode", request.toolCode());
        form.put("version", request.version());
        form.put("invocationLogId", request.invocationLogId());
        form.put("args", request.args() == null ? new LinkedHashMap<String, Object>() : request.args());
        return toJson(form);
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return String.valueOf(value);
        }
    }
}
