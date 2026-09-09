package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 站内通知（审批事件驱动）：
 *   · APPROVAL_SUBMIT  → 发给租户管理员（有待审单）
 *   · APPROVAL_DECIDE  → 发给审批单发起人（通过/驳回 + 意见）
 * read_at 为空 = 未读。
 */
@Data
@TableName("notification")
public class Notification {

    public static final String TYPE_APPROVAL = "APPROVAL";
    public static final String TYPE_SYSTEM = "SYSTEM";
    /** 数字员工定时任务执行完成提醒（弹窗提醒数据源） */
    public static final String TYPE_WORKER = "WORKER";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 接收人 */
    private Long userId;

    private String type;

    private String title;

    private String content;

    /** 关联审批单 id（可空） */
    private Long refId;

    private LocalDateTime readAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
