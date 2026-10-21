package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 会议参会人（邀请状态）：INVITED / ACCEPTED / DECLINED。
 * 与 portal_meeting 同 tenant；唯一键 (meeting_id, user_id)。
 */
@Data
@TableName("portal_meeting_attendee")
public class PortalMeetingAttendee {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long meetingId;

    private Long userId;

    private String inviteStatus;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
