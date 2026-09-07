package cn.aioa.chat.dto;

import lombok.Data;

@Data
public class CreateConversationRequest {

    private String title;

    private String appCode;
}
