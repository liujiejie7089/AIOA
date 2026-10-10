package cn.aioa.chat.dto;

import lombok.Data;

@Data
public class CreateConversationRequest {

    private String title;

    private String appCode;

    /** 绑定的数字员工 ID；非空则本会话受该员工职责边界约束（权限校验在服务层）。 */
    private Long workerId;

    /**
     * 所属项目 ID（V79，可空）。非空 = 项目会话：服务端会硬校验 workerId 必须分配在该项目，
     * 并据项目下发数字人上下文。为空 = 非项目会话（旧行为，不受影响）。
     */
    private Long projectId;
}
