package cn.aioa.resource.service;

import cn.aioa.resource.entity.TenantQuota;
import cn.aioa.resource.entity.TokenLedger;
import cn.aioa.resource.mapper.TenantQuotaMapper;
import cn.aioa.resource.mapper.TokenLedgerMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 词元额度与账本：
 *   · current()         —— 用户端额度条（总额/已用/赠送/剩余）
 *   · ledger()          —— 用量账单（分页，按时间倒序）
 *   · recordUsage()     —— 会话/技能结束后记账，run_id 唯一保证幂等
 * 记账口径：剩余 = quota_tokens + free_tokens - used_tokens
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BillingService {

    /** 未配置额度时的默认套餐额度 */
    private static final long DEFAULT_QUOTA = 100_000L;

    private final TenantQuotaMapper quotaMapper;
    private final TokenLedgerMapper ledgerMapper;

    public record QuotaView(long quota, long used, long free, long left, int percent, boolean exhausted) {
    }

    public record LedgerRow(Long id, String runId, String bizType, String bizTitle,
                            int promptTokens, int completionTokens, int totalTokens,
                            long balanceAfter, LocalDateTime createdAt) {

        static LedgerRow from(TokenLedger t) {
            return new LedgerRow(t.getId(), t.getRunId(), t.getBizType(), t.getBizTitle(),
                    nz(t.getPromptTokens()), nz(t.getCompletionTokens()), nz(t.getTotalTokens()),
                    t.getBalanceAfter() == null ? 0L : t.getBalanceAfter(), t.getCreatedAt());
        }

        private static int nz(Integer v) {
            return v == null ? 0 : v;
        }
    }

    /** 当前额度。优先取用户个人额度，回落到租户共享额度（user_id = 0）。 */
    public QuotaView current(Long tenantId, Long userId) {
        TenantQuota quota = getOrCreate(tenantId, userId);
        long total = nz(quota.getQuotaTokens());
        long used = nz(quota.getUsedTokens());
        long free = nz(quota.getFreeTokens());
        long left = Math.max(0L, total + free - used);
        int percent = total <= 0 ? 0 : (int) Math.min(100L, Math.max(0L, used * 100L / total));
        return new QuotaView(total, used, free, left, percent, left <= 0);
    }

    /** 账本流水（分页）。 */
    public IPage<LedgerRow> ledger(Long tenantId, Long userId, long page, long size) {
        IPage<TokenLedger> p = ledgerMapper.selectPage(new Page<>(page, size),
                new LambdaQueryWrapper<TokenLedger>()
                        .eq(TokenLedger::getTenantId, tenantId)
                        .in(TokenLedger::getUserId, scopeUsers(userId))
                        .orderByDesc(TokenLedger::getCreatedAt));
        return p.convert(LedgerRow::from);
    }

    /** 简化版：取最近 N 条（用户端账单页当前为全量渲染）。 */
    public List<LedgerRow> ledgerTop(Long tenantId, Long userId, int limit) {
        List<TokenLedger> list = ledgerMapper.selectList(new LambdaQueryWrapper<TokenLedger>()
                .eq(TokenLedger::getTenantId, tenantId)
                .in(TokenLedger::getUserId, scopeUsers(userId))
                .orderByDesc(TokenLedger::getCreatedAt)
                .last("limit " + Math.max(1, Math.min(limit, 200))));
        return list.stream().map(LedgerRow::from).toList();
    }

    /**
     * 记一笔消耗。同一 runId 只记一次（uk_token_ledger_run 兜底 + 这里先查一次避免异常扩散）。
     *
     * @return 是否真正记账（false = 重复或零消耗，调用方可忽略）
     */
    @Transactional(rollbackFor = Exception.class)
    public boolean recordUsage(String runId, Long tenantId, Long userId, String bizType, String bizTitle,
                               int promptTokens, int completionTokens) {
        if (runId == null || runId.isBlank()) {
            return false;
        }
        int prompt = Math.max(0, promptTokens);
        int completion = Math.max(0, completionTokens);
        long total = (long) prompt + completion;
        if (total <= 0) {
            return false;
        }
        Long count = ledgerMapper.selectCount(Wrappers.<TokenLedger>lambdaQuery()
                .eq(TokenLedger::getRunId, runId));
        if (count != null && count > 0) {
            log.debug("token ledger already recorded for run {}", runId);
            return false;
        }

        TenantQuota quota = getOrCreate(tenantId, userId);
        quotaMapper.update(null, new LambdaUpdateWrapper<TenantQuota>()
                .eq(TenantQuota::getId, quota.getId())
                .setSql("used_tokens = COALESCE(used_tokens, 0) + " + total));

        TenantQuota after = quotaMapper.selectById(quota.getId());
        long left = Math.max(0L, nz(after.getQuotaTokens()) + nz(after.getFreeTokens()) - nz(after.getUsedTokens()));

        TokenLedger row = new TokenLedger();
        row.setTenantId(tenantId);
        row.setUserId(userId);
        row.setRunId(runId);
        row.setBizType(bizType == null || bizType.isBlank() ? TokenLedger.BIZ_CHAT : bizType);
        row.setBizTitle(bizTitle);
        row.setPromptTokens(prompt);
        row.setCompletionTokens(completion);
        row.setTotalTokens((int) Math.min(total, Integer.MAX_VALUE));
        row.setBalanceAfter(left);
        row.setCreatedAt(LocalDateTime.now());
        row.setCreatedBy(userId);
        ledgerMapper.insert(row);
        return true;
    }

    /** 取额度行；不存在则按默认额度创建（幂等，不抛异常）。 */
    public TenantQuota getOrCreate(Long tenantId, Long userId) {
        long tid = tenantId == null ? 0L : tenantId;
        long uid = userId == null ? 0L : userId;
        TenantQuota quota = quotaMapper.selectOne(new LambdaQueryWrapper<TenantQuota>()
                .eq(TenantQuota::getTenantId, tid)
                .eq(TenantQuota::getUserId, uid));
        if (quota != null) {
            return quota;
        }
        // 个人额度未配置时，回落到租户共享额度，避免为每个用户都建一行
        if (uid != 0L) {
            TenantQuota shared = quotaMapper.selectOne(new LambdaQueryWrapper<TenantQuota>()
                    .eq(TenantQuota::getTenantId, tid)
                    .eq(TenantQuota::getUserId, 0L));
            if (shared != null) {
                return shared;
            }
        }
        TenantQuota created = new TenantQuota();
        created.setTenantId(tid);
        created.setUserId(uid);
        created.setQuotaTokens(DEFAULT_QUOTA);
        created.setUsedTokens(0L);
        created.setFreeTokens(0L);
        created.setCreatedAt(LocalDateTime.now());
        created.setCreatedBy(uid);
        quotaMapper.insert(created);
        return created;
    }

    /** 购买到账：给用户（或租户共享）额度行增加赠送词元（FR-G4 额度实时到账）。 */
    @Transactional(rollbackFor = Exception.class)
    public void addFreeTokens(Long tenantId, Long userId, long tokens) {
        if (tokens <= 0) {
            return;
        }
        TenantQuota quota = getOrCreate(tenantId, userId);
        quotaMapper.update(null, new LambdaUpdateWrapper<TenantQuota>()
                .eq(TenantQuota::getId, quota.getId())
                .setSql("free_tokens = COALESCE(free_tokens, 0) + " + tokens));
    }

    /**
     * 可见用户范围：始终包含 user_id = 0 的租户共享数据（种子数据与共享额度都挂在这里），
     * 再加当前用户自己的数据。否则登录用户（id ≠ 0）会查不到任何预置内容。
     */
    public static List<Long> scopeUsers(Long userId) {
        long uid = userId == null ? 0L : userId;
        return uid == 0L ? List.of(0L) : List.of(0L, uid);
    }

    private static long nz(Long v) {
        return v == null ? 0L : v;
    }
}
