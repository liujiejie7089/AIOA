package cn.aioa.bridge.support;

import cn.aioa.security.AuthUser;

import java.util.Map;

/**
 * 工具调用审批（HITL）扩展点。
 *
 * <p><b>为什么是接口</b>：{@code tool_definition.requires_approval=1} 的工具不能直接执行，
 * 必须先走平台审批流；而审批引擎在 {@code aioa-org}，工具桥接在 {@code aioa-bridge}，
 * 两者是兄弟模块。做法与既有 {@code ExternalToolHandler} / {@code ApprovalCallback} 一致：
 * 桥接模块只定义接口，由同时看得见「工具域」与「审批域」的 {@code aioa-chat} 在组装期实现，
 * 运行期用 {@code ObjectProvider} 惰性取用 —— 编译期零耦合，裁剪掉该实现时
 * 「需审批的工具」会显式报错（而不是悄悄直通执行）。</p>
 *
 * <p><b>为什么必须显式报错</b>：若网关缺失就直通，等于把「高风险工具需审批」这条
 * 治理规则静默降级为「无需审批」，属于安全口径错误，不能以可用性为由放过。</p>
 */
public interface ToolApprovalGateway {

    /**
     * 一次待审批的工具调用。
     *
     * @param tenantId        租户
     * @param applicant       发起调用的用户（作为审批单申请人）
     * @param toolCode        工具编码
     * @param version         工具版本
     * @param title           审批单标题
     * @param args            原始入参（随审批单留存，审批人可据此判断风险）
     * @param invocationLogId 已落库的挂起日志 id（恢复执行时回写同一行）
     */
    record ApprovalRequest(Long tenantId, AuthUser applicant, String toolCode, String version,
                           String title, Map<String, Object> args, Long invocationLogId) {
    }

    /**
     * 提交审批单。
     *
     * @return 审批单 id（{@code approval_order.id}）；返回 null 视为提交失败
     */
    Long submit(ApprovalRequest request);
}
