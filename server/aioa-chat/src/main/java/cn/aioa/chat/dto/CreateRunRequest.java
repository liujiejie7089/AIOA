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

    /** 页面上下文快照（SDK 上报格式）。 */
    private Map<String, Object> context;

    private List<Long> attachments;
}
