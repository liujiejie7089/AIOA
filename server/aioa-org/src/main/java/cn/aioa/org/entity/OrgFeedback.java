package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 投诉与建议（V63）—— 用户端「我的 → 投诉与建议」提交的反馈。
 *
 * <p>表：{@code org_feedback}。一条记录的完整生命周期：</p>
 * <ol>
 *   <li>用户提交 → 系统按「本部门管理员 → 本机构管理员 → 租户管理员」<b>逐级上溯</b>
 *       解析出接收人，写入 {@link #assigneeUserId} 与 {@link #assigneeScope}/{@link #assigneeReason}；</li>
 *   <li>同时给接收人发一条站内通知（{@code NotificationService}），让他知道有新反馈；</li>
 *   <li>接收人回复 → 状态转 {@link #STATUS_REPLIED}，{@link #replyContent} 对提交人可见。</li>
 * </ol>
 *
 * <p><b>为什么接收层级必须落库</b>：上溯是一次有分支的判定 —— 同一句话在不同组织下会派给不同人。
 * 只发通知不记录，事后永远说不清「这条为什么没人处理」。记录 {@code assigneeScope}
 * 让「派到了租户级」这件事本身成为可见事实（那通常意味着该部门/机构缺管理员，是组织问题不是分配 bug）。</p>
 *
 * <p><b>匿名的边界</b>：{@code anonymous=1} 只影响「上级查看时是否展示提交人姓名」，
 * {@link #submitterUserId} 仍然保留 —— 否则无法把答复送还给提交人，也无法防刷。
 * 这条边界必须在实现里守住，不能因为「用户选了匿名」就把外键抹掉。</p>
 */
@Data
@TableName("org_feedback")
public class OrgFeedback {

    public static final String CATEGORY_COMPLAINT = "COMPLAINT";
    public static final String CATEGORY_ADVICE = "ADVICE";
    public static final String CATEGORY_BUG = "BUG";
    public static final String CATEGORY_SERVICE = "SERVICE";
    public static final String CATEGORY_OTHER = "OTHER";

    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_REPLIED = "REPLIED";
    public static final String STATUS_CLOSED = "CLOSED";

    /** 接收人实际命中的层级。 */
    public static final String SCOPE_DEPT = "DEPT";
    public static final String SCOPE_INSTITUTION = "INSTITUTION";
    public static final String SCOPE_TENANT = "TENANT";
    /** 逐级上溯到租户级仍无人可派 —— 待人工指派，不是「已送达」。 */
    public static final String SCOPE_NONE = "NONE";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private Long departmentId;

    private String category;

    private String content;

    private String contact;

    private Boolean anonymous;

    private String status;

    private Long submitterUserId;

    private String submitterName;

    private String submitterDeptName;

    private Long assigneeUserId;

    private String assigneeName;

    private String assigneeScope;

    private String assigneeReason;

    private String replyContent;

    private Long repliedBy;

    private String repliedByName;

    private LocalDateTime repliedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
