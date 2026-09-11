package cn.aioa.chat.dto;

import lombok.Data;

@Data
public class CreateConversationRequest {

    private String title;

    private String appCode;

    /** 绑定的数字员工 ID；非空则本会话受该员工职责边界约束（权限校验在服务层）。 */
    private Long workerId;
}
