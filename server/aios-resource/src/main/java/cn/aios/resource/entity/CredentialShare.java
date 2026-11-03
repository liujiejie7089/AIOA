package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 模型账号共享授权（主账号 → 子账号）。
 *
 * <p>语义：{@code ownerUserId} 把自己的账号（{@code credentialId}）授权给
 * {@code granteeUserId} 使用，<b>被邀请人消耗的词元由邀请者承担</b> ——
 * 这条在数据上的唯一体现是记账时 {@code token_ledger.charge_user_id = ownerUserId}，
 * 而非扣被邀请人自己的额度。</p>
 *
 * <p>撤销后再次邀请<b>复用同一行</b>（改状态、清 {@code revokedAt}）：
 * 唯一键 {@code (credential_id, grantee_user_id)} 会挡住插入，
 * 而复用行还能保留「曾经撤销过一次」的时间线。</p>
 */
@Data
@TableName("credential_share")
public class CredentialShare {

    /** 已邀未接受（邀请码未使用）。 */
    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_ACTIVE = "ACTIVE";
    public static final String STATUS_REVOKED = "REVOKED";
    public static final String STATUS_EXPIRED = "EXPIRED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long credentialId;

    /** 邀请者 = 承担人 */
    private Long ownerUserId;

    private Long granteeUserId;

    private String granteeName;

    private String status;

    private String inviteCode;

    /** 该子账号的共享上限，0 = 不限 */
    private Long quotaTokens;

    /** 已用量（加速上限判断；账本仍是唯一事实源） */
    private Long usedTokens;

    private LocalDateTime expiresAt;

    private LocalDateTime acceptedAt;

    private LocalDateTime revokedAt;

    private LocalDateTime createdAt;

    private Long createdBy;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;

    /**
     * 当前是否可用：ACTIVE 且未过期。
     *
     * <p>到期判定放在<b>读时</b>（{@code expiresAt < now} ⇒ 视为失效），
     * 不依赖定时任务 —— 否则「昨天到期、任务今天还没跑」这段时间里共享仍然有效。</p>
     */
    public boolean usable(LocalDateTime now) {
        if (!STATUS_ACTIVE.equalsIgnoreCase(status)) {
            return false;
        }
        return expiresAt == null || expiresAt.isAfter(now == null ? LocalDateTime.now() : now);
    }

    /** 是否已用尽共享上限（quotaTokens = 0 表示不限）。 */
    public boolean exhausted() {
        if (quotaTokens == null || quotaTokens <= 0) {
            return false;
        }
        long used = usedTokens == null ? 0L : usedTokens;
        return used >= quotaTokens;
    }
}
