package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 项目任务（业务任务）。
 *
 * <p>表 {@code pm_task}（V71）。</p>
 *
 * <p><b>⚠ 与 {@code gitee_task} 无关</b>：{@code gitee_task} 是**异步任务队列（outbox）**
 * （{@code task_type=CREATE_REPO/SYNC_MEMBER/...}，由调度器消费），本表是**人做的业务任务**。
 * 两者同名不同物，任何一处把它俩混用（例：以为建业务任务会触发建仓）都会造成静默错行为。</p>
 *
 * <p><b>仓库关联字段（{@code repo_*}）只对开发项目有意义</b>：业务项目写这些列会被
 * {@code ProjectTypeGuard} 拦成 400（BR-01），且 {@code repo_id} 与 {@code repo_issue_no}
 * 必须成对出现或成对为空（BR-12）。</p>
 */
@Data
@TableName("pm_task")
public class PmTask {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** 父任务 id（子任务），本期最多两级。 */
    private Long parentId;

    private String title;

    /** 描述。允许改空，故 ALWAYS（同 PmProject.description 的理由）。 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String description;

    /** 见 {@link cn.aioa.project.support.PmTaskStatus}。 */
    private String status;

    /** LOW / MEDIUM / HIGH / URGENT。 */
    private String priority;

    /** 负责人 {@code org_member.id}。 */
    private Long assigneeMemberId;

    private LocalDate startDate;

    private LocalDate dueDate;

    /** 进度 0-100。 */
    private Integer progress;

    /** {@code gitee_project.id}；仅开发项目。解绑/改字段时置空 —— 故 ALWAYS。 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private Long repoId;

    /** 关联 issue 号；仅开发项目，与 {@link #repoId} 成对。 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String repoIssueNo;

    /** 分支名；仅开发项目。 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String repoBranch;

    /** 关联提交 SHA；仅开发项目。 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String repoCommitSha;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
