package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 成果沉淀（V1.2 新增）：会话产出「存为成果」后可继续编辑 / 发起审批 / 转发。
 * status：DRAFT 草稿 → SUBMITTED 审批中 → APPROVED 已通过。
 */
@Data
@TableName("user_result")
public class UserResult {

    public static final String STATUS_DRAFT = "DRAFT";
    public static final String STATUS_SUBMITTED = "SUBMITTED";
    public static final String STATUS_APPROVED = "APPROVED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    private String title;

    /** 图标键（doc / sheet / slide），前端映射矢量图标 */
    private String icon;

    private String meta;

    private String body;

    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
