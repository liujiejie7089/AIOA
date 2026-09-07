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

    private Map<String, Object> context;

    @JsonProperty("agent_code")
    private String agentCode;

    @JsonProperty("model_ref")
    private String modelRef;

    @JsonProperty("user_context")
    private AgentUserContext userContext;
}
