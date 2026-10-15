package cn.aioa.chat.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class CreateRunRequest {

    private String text;

    /** 模型路由（FR-C4 模型切换）：写入会话 model_ref，Agent 侧按此选 provider。 */
    @JsonProperty("model_ref")
    private String modelRef;

    /**
     * 对话级知识库开关（顶层字段）：下发 Agent 侧控制本轮是否启用知识库检索。
     * 缺失时回落到 {@code context.kb_on}（历史写法），二者皆无则保持 null（Agent 侧缺省当「开」）。
     */
    @JsonProperty("kb_on")
    private Boolean kbOn;

    /** 页面上下文快照（SDK 上报格式）。 */
    private Map<String, Object> context;

    private List<Long> attachments;
}
