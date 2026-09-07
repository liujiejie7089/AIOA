package cn.aioa.chat.dto;

import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class CreateRunRequest {

    private String text;

    /** 页面上下文快照（SDK 上报格式）。 */
    private Map<String, Object> context;

    private List<Long> attachments;
}
