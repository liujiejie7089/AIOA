package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 项目成员 + 项目内角色。
 *
 * <p>表 {@code pm_project_member}（V71）。</p>
 *
 * <p><b>两套「角色」不要混</b>：</p>
 * <ul>
 *   <li>{@code sys_role}（系统角色，如 {@code ROLE_ORG_ADMIN}）：决定「能进哪些页面 / 调哪些接口」，
 *       存在 {@code AuthUser.roles}；</li>
 *   <li>{@code role_code}（本表，项目内角色 OWNER/PM/DEV/MEMBER/VIEWER）：决定「在这个项目里能做什么」。
 *       它不是系统角色，不会出现在 {@code AuthUser.roles} 里，只能由服务层按 {@code project_id} 查本表判定。</li>
 * </ul>
 * 混用二者是越权的经典入口（例：把项目内 {@code PM} 当成系统角色发出去 ⇒ 该用户在所有项目里都是 PM）。
 *
 * <p><b>{@code member_id} 是 {@code org_member.id} 而非 {@code sys_user.id}</b>：
 * 项目成员必须是「在册员工」（BR-03）。用 user_id 会造成「离职了但仍是项目成员」（员工软删后
 * user_id 指向的账号仍在），用 member_id 则员工一软删、成员关系自然失去依据。</p>
 */
@Data
@TableName("pm_project_member")
public class PmProjectMember {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** {@code org_member.id}（在册员工）。 */
    private Long memberId;

    /** 冗余 {@code sys_user.id}，用于「我参与的项目」快速过滤；员工换绑账号时随之更新。 */
    private Long userId;

    /** 项目内角色，见 {@link cn.aioa.project.support.PmProjectRoles}。 */
    private String roleCode;

    /**
     * 仓库协作者同步态：{@code NA} 业务项目无仓库 / {@code SYNCED} / {@code PENDING} / {@code FAILED}。
     *
     * <p>开发项目成员变更后异步同步为仓库协作者。**同步失败不回滚成员关系**，只把本列置 FAILED，
     * 界面给「重试」——成员关系是业务事实，仓库协作者只是它的一个副作用投影，
     * 让副作用失败回滚业务事实会把「加个人」变成随时可能失败的脆弱操作。</p>
     */
    private String repoSyncStatus;

    private LocalDate joinedAt;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
