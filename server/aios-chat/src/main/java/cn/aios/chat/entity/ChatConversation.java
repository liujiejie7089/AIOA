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

    /**
     * 置顶（V108）：1 = 在本人的「最近」列表里固定在最上方。
     *
     * <p>为什么落库而不是放前端 localStorage：换设备/换浏览器就丢，而「置顶」是用户
     * 对工作内容的整理结果，属于会话元数据的一部分。列非空默认 0 ⇒ 旧数据行为零变化。</p>
     */
    private Integer pinned;

    /** 置顶时刻：多条置顶之间按它倒序（后置顶的排更上），避免顺序乱跳。 */
    private LocalDateTime pinnedAt;

    /**
     * 标题来源（V108）：{@code AUTO}=由用户第一句问题自动总结 / {@code CREATE}=创建方指定 /
     * {@code MANUAL}=用户手动重命名。
     *
     * <p>为什么要单独一列：脚本与集成方 create 时会传技术名（{@code grade-sheet-probe}、
     * {@code enum-probe}），而用户要看到的是「我问了什么」。只看 title 字符串分不清
     * 「技术名」与「用户改过的名」—— 前者该被首轮问题覆盖，后者必须尊重。
     * 判据：首轮对话时只要 {@code titleSource != MANUAL} 就重写标题。</p>
     */
    private String titleSource;

    public static final String TITLE_AUTO = "AUTO";
    public static final String TITLE_CREATE = "CREATE";
    public static final String TITLE_MANUAL = "MANUAL";
}
