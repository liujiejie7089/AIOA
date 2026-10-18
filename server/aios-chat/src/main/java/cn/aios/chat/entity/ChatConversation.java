package cn.aios.chat.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("chat_conversation")
public class ChatConversation {

    public static final String STATUS_ACTIVE = "ACTIVE";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long userId;
    private String title;
    private String agentCode;
    private String appCode;

    /**
     * 所属项目 ID（V79）：NULL = 非项目会话（经典形态 / 无项目对话坞）。
     *
     * <p>非空表示该会话属于某项目，聊天链路据此：① 校验绑定的数字员工确实分配在该项目
     * （否则 403）；② 下发该项目的生效上下文（见 {@code RunService.buildScope}）。
     * 这是用户端「不同项目数据隔离」的服务端锚点。</p>
     */
    private Long projectId;

    /**
     * 绑定的数字员工 ID（V21）：非空表示该会话受该数字员工的职责边界约束，
     * Agent 侧会注入职责范围系统提示，只回答职责范围内的问题。
     */
    private Long workerId;

    /**
     * 本会话所属专家 ai_expert.expert_key（V88）：NULL = 未选专家（走默认 AI）。
     *
     * <p>会话级专家落库点：用户在 H5 选的「专家 AI」经 {@code RunService#start} 解析为库里
     * 真实存在的 expert_key 后写回本列，使每一轮（subscribe 重新取 conversation）都能按此列下发
     * 专家人设（{@code AgentRunRequest.expert} + 专家运行参数）。专家会话不绑数字员工，
     * worker 职责边界优先于专家人设（见 {@code RunService#subscribe} 的 else-if 判定）。</p>
     */
    private String expertKey;

    private String modelRef;
    private String summary;
    private Integer contextTurns;
    private Long msgCount;
    private String status;
    private LocalDateTime lastMsgAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private LocalDateTime deletedAt;
}
