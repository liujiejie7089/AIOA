package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 管理端首页会议（含组织者）。
 * status：SCHEDULED / CANCELED / FINISHED。
 */
@Data
@TableName("portal_meeting")
public class PortalMeeting {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String title;

    private LocalDateTime startAt;

    private LocalDateTime endAt;

    private String location;

    private Long organizerId;

    private String organizerName;

    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
