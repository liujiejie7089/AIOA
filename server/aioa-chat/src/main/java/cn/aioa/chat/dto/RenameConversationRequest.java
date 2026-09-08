package cn.aioa.chat.dto;

import lombok.Data;

/** FR-D3 会话重命名请求体。 */
@Data
public class RenameConversationRequest {

    private String title;
}
