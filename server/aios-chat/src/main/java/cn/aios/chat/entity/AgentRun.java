package cn.aios.chat.entity;

import cn.aios.common.mybatis.JsonMapTypeHandler;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;

@Data
@TableName(value = "agent_run", autoResultMap = true)
public class AgentRun {

    public static final String STATUS_RUNNING = "RUNNING";
    public static final String STATUS_SUCCEEDED = "SUCCEEDED";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_CANCELLED = "CANCELLED";

    /**
     * 等待人在环（HITL）澄清回填：模型调用 ask_user 后图在 clarify 节点 interrupt() 暂停，
     * 本轮 SSE 流已正常结束（暂停时**不发** run.completed）。run 处于挂起态：
     *   · 它**不是** RUNNING —— 既不在跑、也不在产出 token；
     *   · 它也**不能**靠重复订阅恢复 —— 同一 thread_id 会覆盖 agent 侧断点，
     *     使已完成的工具调用面临重跑风险（HITL 验收判据 Q3）。
     * 挂起中的 run 只能由 {@code /api/v1/runs/{runId}/resume} 回填澄清卡后从断点续跑，
     * 重复 subscribe 必须被拦截（见 RunService.waitingInputNotice）。
     */
    public static final String STATUS_WAITING_INPUT = "WAITING_INPUT";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String runId;
    private Long conversationId;
    private Long userId;
    private String status;
    @TableField(typeHandler = JsonMapTypeHandler.class)
    private Map<String, Object> plan;
    private Integer currentStep;
    private String error;
    private Integer tokensIn;
    private Integer tokensOut;
    private LocalDateTime startedAt;
    private LocalDateTime endedAt;
    private Long durationMs;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
