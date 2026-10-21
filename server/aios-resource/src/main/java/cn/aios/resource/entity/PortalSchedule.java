package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 个人日程（属主 user_id）。按 tenant + user_id 隔离，并叠加平台公共 tenant_id=0。
 */
@Data
@TableName("portal_schedule")
public class PortalSchedule {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    private String title;

    private LocalDateTime startAt;

    private LocalDateTime endAt;

    private String location;

    private String remark;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
