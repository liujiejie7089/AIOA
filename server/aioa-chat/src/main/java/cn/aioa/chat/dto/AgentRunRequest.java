package cn.aioa.chat.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * internal-agent.yaml 的 RunRequest（Java → Python）。
 */
@Data
public class AgentRunRequest {

    @JsonProperty("run_id")
    private String runId;

    @JsonProperty("conversation_id")
    private Long conversationId;

    private String text;

    private List<Long> attachments;

    /**
     * 对话内上传文档（不进知识库）的参考正文，下发 Agent 侧供本轮回答参考。
     * 与 {@code attachments}（仅 id）不同，这里携带已解析的 {file_id,name,text,truncated}，
     * 键名 {@code attachment_docs} 必须与此处 @JsonProperty 一致（agent 侧 RunRequest.attachment_docs 契约）。
     */
    @JsonProperty("attachment_docs")
    private List<Map<String, Object>> attachmentDocs;

    private Map<String, Object> context;

    @JsonProperty("agent_code")
    private String agentCode;

    @JsonProperty("model_ref")
    private String modelRef;

    @JsonProperty("user_context")
    private AgentUserContext userContext;

    /**
     * 发起 run 的用户 accessToken（M2 工具回调）：Agent 调用业务工具网关
     * /api/v1/tools/* 时透传，工具权限 = 用户权限。
     */
    @JsonProperty("user_token")
    private String userToken;

    /**
     * 多轮会话历史（FR-C2）：近 N 轮 user/assistant 消息，按时间正序，
     * 不含本轮提问。Agent 侧拼入模型上下文，实现跨轮记忆。
     */
    @JsonProperty("history")
    private List<ChatTurn> history;

    /**
     * 职责范围（V21）：会话绑定数字员工时下发。Agent 侧据此注入「职责范围」系统提示，
     * 只回答与该数字员工职责相关的问题，越界一律礼貌拒答。
     * 键：worker_id / name / role / role_name / duty / permission（见 WorkerRole）。
     */
    private Map<String, Object> scope;

    /**
     * 当前项目简报（下发 Agent 侧供本轮回答参考）：由后端在「项目会话」里下发，
     * 键名照抄后端契约 {@code PmAiScopePort.projectBrief}：{@code id / name / type / status}。
     * 不绑定数字员工的项目会话同样会携带，避免 Agent 反问「上传到哪个系统或平台」；
     * 项目名以库为准，不由前端传入。
     */
    @JsonProperty("project")
    private Map<String, Object> project;

    /** 一条历史消息（role ∈ user/assistant）。 */
    public record ChatTurn(String role, String content) {
    }
}
