package cn.aioa.bridge.entity;

import cn.aioa.common.mybatis.JsonMapTypeHandler;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 工具调用日志。
 *
 * <p>一次调用的完整生命周期都落在这里（V59 起真正有数据）：</p>
 * <ul>
 *   <li>{@code error_code='PENDING_APPROVAL'} 的行 = 已挂起等待审批；{@code args_masked}
 *       保存了原始入参、{@code approval_id} 保存了审批单号，审批通过后由
 *       「恢复执行」按 {@code approval_id} 取回并继续；</li>
 *   <li>{@code idempotency_key} 与 (tenant_id, tool_code) 组成唯一键，
 *       同键重复调用直接回放 {@code result_body}，不会重复触发外部副作用；</li>
 *   <li>{@code result_body} 为响应体原文（已按 {@code max_bytes} 截断），
 *       既支撑幂等重放，也便于事后排查「工具到底返回了什么」。</li>
 * </ul>
 */
@Data
@TableName(value = "tool_invocation_log", autoResultMap = true)
public class ToolInvocationLog {

    /** 挂起等待审批：该行尚未真正调用外部系统。 */
    public static final String ERROR_PENDING_APPROVAL = "PENDING_APPROVAL";
    /** 权限闸门拒绝：未到达外部系统。 */
    public static final String ERROR_PERMISSION_DENIED = "PERMISSION_DENIED";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String traceId;
    private String runId;
    private Long stepId;
    private String toolCode;
    private String version;
    private Long userId;
    /** 入参的<b>脱敏</b>拷贝（敏感键值替换为 ***），仅用于审计展示。 */
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> argsMasked;
    /** 挂起等待审批时的<b>原始</b>入参，审批通过后据此恢复执行（不脱敏，否则无法重放）。 */
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> pendingArgs;
    private String resultDigest;
    private Long resultSize;
    /** 响应体原文（按 max_bytes 截断），供幂等重放与事后排查。 */
    private String resultBody;
    /** 调用方幂等键；idempotency_required=1 的工具必填。 */
    private String idempotencyKey;
    private Integer httpStatus;
    private Long durationMs;
    private String approvalId;
    private String errorCode;
    private LocalDateTime createdAt;
}
