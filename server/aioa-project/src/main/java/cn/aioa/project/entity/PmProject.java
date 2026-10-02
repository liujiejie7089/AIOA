package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 项目主表（业务项目与开发项目共用）。
 *
 * <p>表 {@code pm_project}（V71）。设计依据见 {@code docs/40 §6.1}。</p>
 *
 * <p><b>为什么两种项目类型共用一张表</b>：二者 90% 的字段相同（编号/名称/归属/负责人/预算/起止），
 * 差异只在「是否绑代码仓库」，而仓库绑定已由 {@code gitee_project.pm_project_id} 承载。
 * 拆两张表会让「项目列表」永远要做 UNION、成员/任务/合同的外键也要二选一，
 * 复杂度远超它解决的问题。差异改由 {@code project_type} 一个字段驱动（见 {@code ProjectTypeGuard}）。</p>
 *
 * <p><b>生成列 {@code alive} 不映射</b>：它是 MySQL 虚拟生成列，实体里带上会让 MyBatis-Plus
 * 尝试写它而报错（V24 迁移已写明此约定）。</p>
 */
@Data
@TableName("pm_project")
public class PmProject {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 项目编号（租户内唯一，软删行不占号 —— 唯一键含 alive）。 */
    private String projectNo;

    private String name;

    /** BUSINESS 业务项目 / DEV 开发项目（见 {@link cn.aioa.project.support.PmProjectType}）。 */
    private String projectType;

    /** 见 {@link cn.aioa.project.support.PmProjectStatus}。 */
    private String status;

    private Long institutionId;

    private Long departmentId;

    /** 项目负责人：{@code org_member.id}（不是 sys_user.id）。 */
    private Long ownerMemberId;

    /** 预算总额（计划值）。实际发生额在 {@code pm_expense}，此处只存计划。 */
    private BigDecimal budgetAmount;

    private LocalDate startDate;

    private LocalDate endDate;

    /** 描述。允许改空 —— 故更新策略 ALWAYS，否则「清空描述」会被默认的 NOT_NULL 策略静默丢弃。 */
    @TableField(updateStrategy = com.baomidou.mybatisplus.annotation.FieldStrategy.ALWAYS)
    private String description;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
