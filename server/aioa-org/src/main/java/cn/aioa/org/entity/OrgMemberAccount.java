package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 员工 ↔ 用户账号（多对多，V67 / docs/38 批次 C）。
 *
 * <p>表：{@code org_member_account}。规格原话：「一个员工也可以有多个用户帐号」，
 * 而此前只有 {@code org_member.user_id} 这一个单值外键，多账号只能用"多建一行员工"来近似 ——
 * 那会把「一个人」拆成「多个人」，连带把部门人数、审批人、统计口径全带偏。</p>
 *
 * <p><b>与 {@code org_member.user_id} 的关系</b>：后者仍是**主账号**，是通知/审批/鉴权/机构归属
 * 等既有 20+ 处读的唯一口径，本批不动它。中间表里 {@code is_primary=1} 的那一行与它**同源**，
 * 由 {@code MemberAccountService} 在开户/改绑时同步维护；**不允许只写一边**。</p>
 *
 * <p>「虚拟管理员账号」（无对应员工的账号）不需要在本表留行 —— 判据就是「本表查不到」，
 * 因此不新增列（docs/38 §3 假设 6）。</p>
 */
@Data
@TableName("org_member_account")
public class OrgMemberAccount {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 冗余租户维度，便于按租户过滤；写入时由服务层从 member 取，不接受请求体传入。 */
    private Long tenantId;

    /** {@code org_member.id} */
    private Long memberId;

    /** {@code sys_user.id} */
    private Long userId;

    /** 是否该员工的主账号（1=是）。与 {@code org_member.user_id} 同源。 */
    private Integer isPrimary;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
