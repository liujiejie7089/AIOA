package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 管理端首页公告（平台 tenant_id=0 公共 + 各租户自有）。
 * status：PUBLISHED / OFFLINE；列表仅出 PUBLISHED。
 */
@Data
@TableName("portal_announcement")
public class PortalAnnouncement {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String title;

    private String category;

    private String content;

    private String publisherName;

    private LocalDateTime publishAt;

    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
