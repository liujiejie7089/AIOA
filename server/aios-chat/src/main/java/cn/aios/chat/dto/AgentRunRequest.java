package cn.aios.chat.dto;

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

    /**
     * 对话级知识库开关：顶层下发 Agent 侧，控制本轮是否启用知识库检索。
     * 键名 {@code kb_on} 必须与此处 @JsonProperty 一致（agent 侧 RunRequest.kb_on 契约）。
     * 缺省（null）由 Agent 侧当作「开」，后端不补默认值。
     */
    @JsonProperty("kb_on")
    private Boolean kbOn;

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
     * 数字人（worker）专属运行参数：后端从 ai_expert 解析后下发，agent 侧据此驱动推理/检索
     * （键名与 ExpertSettings 模型字段一致：model / temperature / topK / threshold / retrievalMode / ...）。
     * 顶层字段（非 scope 内键）：agent 侧 {@code RunRequest.expert_settings} 直接读取，
     * scope 内的键会被当作职责范围而非运行参数。
     * 「取不到 = 不注入」（保持 agent 默认值），绝不注入空对象——空对象会让 agent 侧
     * {@code es.get(...)} 拿到空串把 ExpertSettings 的默认值打掉。
     */
    @JsonProperty("expert_settings")
    private Map<String, Object> expertSettings;

    /**
     * 当前项目简报（下发 Agent 侧供本轮回答参考）：由后端在「项目会话」里下发，
     * 键名照抄后端契约 {@code PmAiScopePort.projectBrief}：{@code id / name / type / status}。
     * 不绑定数字员工的项目会话同样会携带，避免 Agent 反问「上传到哪个系统或平台」；
     * 项目名以库为准，不由前端传入。
     */
    @JsonProperty("project")
    private Map<String, Object> project;

    /**
     * 当前租户可用表单清单（agent 据此选 form_code，避免编造）：[{code,name,module_code,biz_type}]。
     * 由后端在 start 里注入（清单为空则不注入，保持改动前逐字节一致）。
     */
    @JsonProperty("available_forms")
    private List<Map<String, Object>> availableForms;

    /**
     * 确定性开表提示 `{form_code, reason}`：当「该数字人只绑一张表 + 用户原话点名了这项任务」
     * 时由后端判定并下发。agent 在模型没有自己调 request_form 的收尾轮据此在图里补一次
     * 真实 `interrupt()` —— 只有图里有断点，用户提交表单后 `/resume` 才能续跑。
     * 判定只在后端一处（{@code RunService#shouldOpenSingleForm}），agent 只执行。
     */
    @JsonProperty("form_hint")
    private Map<String, Object> formHint;

    /**
     * 会话内跨数字人转交（handoff）通知：当一轮对话命中转交时由后端下发，
     * 键：from_worker_id / from_worker_name / to_worker_id / to_worker_name / task_name / question。
     * Agent 侧据此在系统提示里追加「此前由某数字人接待、现已转交给您，请勿要求用户重述」的说明。
     * 顶层字段（agent 侧 {@code RunRequest.handoff} 直接读取）；为空（无转交）时该字段不下发（null）。
     */
    @JsonProperty("handoff")
    private Map<String, Object> handoff;

    /**
     * 会话级专家画像（V88 链路补齐）：后端按 chat_conversation.expert_key 解析 ai_expert 后下发，
     * 键名照抄后端契约：{@code key / name / summary / intro / tags / recs / system_prompt / knowledge_scope}。
     * 顶层字段（非 scope 内键）：agent 侧 {@code RunRequest.expert} 直接读取；
     * scope 内的键会被当作职责范围而非专家画像。
     * 「取不到 = 不注入」（保持 agent 默认值），绝不注入空对象——空对象会把 agent 侧默认值打掉。
     * 与 system_prompt 同义的 expert_settings.systemPrompt 仅作兜底，主来源是本字段的 system_prompt。
     */
    @JsonProperty("expert")
    private Map<String, Object> expert;

    /** 一条历史消息（role ∈ user/assistant）。 */
    public record ChatTurn(String role, String content) {
    }
}
