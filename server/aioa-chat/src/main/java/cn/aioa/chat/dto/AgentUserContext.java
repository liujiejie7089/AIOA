package cn.aioa.chat.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.util.List;

/**
 * internal-agent.yaml 的 UserContext。
 */
@Data
public class AgentUserContext {

    @JsonProperty("user_id")
    private Long userId;

    @JsonProperty("tenant_id")
    private Long tenantId;

    private String username;

    private List<String> roles;

    @JsonProperty("trace_id")
    private String traceId;
}
