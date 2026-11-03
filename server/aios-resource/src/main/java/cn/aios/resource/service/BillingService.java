package cn.aios.resource.service;

import cn.aios.resource.entity.ModelCredential;
import cn.aios.resource.entity.TenantQuota;
import cn.aios.resource.entity.TokenLedger;
import cn.aios.resource.mapper.TenantQuotaMapper;
import cn.aios.resource.mapper.TokenLedgerMapper;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

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

    /**
     * 一笔消耗的归属上下文（2026-11-03，docs/71）。
     *
     * <p><b>为什么参数不直接是「companyCharged 布尔值」</b>：那样调用方就能决定「这笔算不算公司收费」，
     * 账单口径立刻可被伪造。这里只收 {@code ownerType}（凭证来源，来自库里那一行），
     * 由 {@link #companyChargedOf(String)} 一处推导 —— 推导规则只有一份。</p>
     *
     * @param credentialId  本次使用的模型账号；null = 走平台默认通道
     * @param bearerUserId  实际使用者（发起人）
     * @param chargeUserId  平台侧承担者：PERSONAL = 账号持有人；COMPANY = 0（公司池）
     * @param ownerType     PERSONAL / COMPANY；null = 未标注（历史或平台默认通道）
     */
    public record ChargeContext(Long credentialId, Long bearerUserId, Long chargeUserId,
                                String ownerType, String providerKey, String modelName) {

        /** 未绑定任何账号（走平台默认通道）：使用者即承担者，收费归属未标注。 */
        public static ChargeContext unbound(Long userId) {
            return new ChargeContext(null, userId, userId, null, null, null);
        }
    }

    /** 是否公司收费：**只看凭证来源**，PERSONAL→0、COMPANY→1、未标注→null。 */
    public static Integer companyChargedOf(String ownerType) {
        if (ownerType == null || ownerType.isBlank()) {
            return null;
        }
        return ModelCredential.OWNER_COMPANY.equalsIgnoreCase(ownerType) ? 1 : 0;
    }

    public record LedgerRow(Long id, String runId, String bizType, String bizTitle,
                            int promptTokens, int completionTokens, int totalTokens,
                            long balanceAfter, LocalDateTime createdAt,
                            Long credentialId, Long bearerUserId, Long chargeUserId,
                            String chargeOwnerType, Integer companyCharged,
                            String providerKey, String modelName) {

        static LedgerRow from(TokenLedger t) {
            return new LedgerRow(t.getId(), t.getRunId(), t.getBizType(), t.getBizTitle(),
                    nz(t.getPromptTokens()), nz(t.getCompletionTokens()), nz(t.getTotalTokens()),
                    t.getBalanceAfter() == null ? 0L : t.getBalanceAfter(), t.getCreatedAt(),
                    t.getCredentialId(), t.getBearerUserId(), t.getChargeUserId(),
                    t.getChargeOwnerType(), t.getCompanyCharged(),
                    t.getProviderKey(), t.getModelName());
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
    public boolean recordUsage(String runId, Long tenantId, Long userId, String bizType, String bizTitle,
                               int promptTokens, int completionTokens) {
        return recordUsage(runId, tenantId, userId, bizType, bizTitle, promptTokens, completionTokens, null);
    }

    /**
     * 记一笔消耗（带归属）。{@code charge == null} 等价于「未标注」的历史口径。
     *
     * <p><b>扣减的行与记账的名不是同一行</b>：账本 {@code user_id} 记<b>使用者</b>（可追人），
     * 额度行扣<b>承担者</b>（谁付钱）。被邀请同事用别人的账号时，
     * 这两者必然不同 —— 这正是本方法存在的理由。</p>
     *
     * <p>{@code balanceAfter} 取<b>承担者</b>的余额：账单上「这笔之后还剩多少」
     * 指的永远是付钱那一方的余额，不是使用者的。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public boolean recordUsage(String runId, Long tenantId, Long userId, String bizType, String bizTitle,
                               int promptTokens, int completionTokens, ChargeContext charge) {
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

        // 承担者：有归属上下文就按它；没有则沿用「使用者即承担者」的旧口径。
        Long bearerId = charge != null && charge.bearerUserId() != null ? charge.bearerUserId() : userId;
        Long chargeId = charge != null && charge.chargeUserId() != null ? charge.chargeUserId() : userId;

        TenantQuota quota = getOrCreate(tenantId, chargeId);
        quotaMapper.update(null, new LambdaUpdateWrapper<TenantQuota>()
                .eq(TenantQuota::getId, quota.getId())
                .setSql("used_tokens = COALESCE(used_tokens, 0) + " + total));

        TenantQuota after = quotaMapper.selectById(quota.getId());
        long left = Math.max(0L, nz(after.getQuotaTokens()) + nz(after.getFreeTokens()) - nz(after.getUsedTokens()));

        TokenLedger row = new TokenLedger();
        row.setTenantId(tenantId);
        row.setUserId(bearerId);
        row.setCredentialId(charge == null ? null : charge.credentialId());
        row.setBearerUserId(bearerId);
        row.setChargeUserId(chargeId);
        row.setChargeOwnerType(charge == null ? null : charge.ownerType());
        row.setCompanyCharged(charge == null ? null : companyChargedOf(charge.ownerType()));
        row.setProviderKey(charge == null ? null : charge.providerKey());
        row.setModelName(charge == null ? null : charge.modelName());
        row.setRunId(runId);
        row.setBizType(bizType == null || bizType.isBlank() ? TokenLedger.BIZ_CHAT : bizType);
        row.setBizTitle(bizTitle);
        row.setPromptTokens(prompt);
        row.setCompletionTokens(completion);
        row.setTotalTokens((int) Math.min(total, Integer.MAX_VALUE));
        row.setBalanceAfter(left);
        row.setCreatedAt(LocalDateTime.now());
        row.setCreatedBy(bearerId);
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

    // ---------- 归属统计（2026-11-03，docs/71 §7） ----------

    /** 一行统计：key/名称/来源/是否公司收费/词元/调用次数/涉及人数。 */
    public record StatsRow(String key, String name, String ownerType, Integer companyCharged,
                           long tokens, long calls, int members) {
    }

    /**
     * 「是否公司收费」三段汇总。与维度无关，任何统计都带这一块。
     *
     * <p>{@code unmarked} 单列：历史账本没记归属，补 0 等于谎报「个人自付」，
     * 宁可让页面显示「未标注」。</p>
     */
    public record ChargedSplit(long companyCharged, long personalCharged, long unmarked,
                               long total, long calls) {
    }

    public record StatsView(String dim, String period, LocalDateTime since, LocalDateTime until,
                            List<StatsRow> rows, ChargedSplit split) {
    }

    /**
     * 按维度聚合用量。三个维度共用同一批账本（合计恒等），页面不得二次加工。
     *
     * @param dim credential 按账号 / bearer 按使用者 / charge 按付费人
     */
    public StatsView stats(Long tenantId, String dim, LocalDateTime since, LocalDateTime until) {
        List<Map<String, Object>> rows = switch (dim == null ? "" : dim.trim().toLowerCase(java.util.Locale.ROOT)) {
            case "credential" -> ledgerMapper.selectStatsByCredential(tenantId, since, until);
            case "charge" -> ledgerMapper.selectStatsByCharge(tenantId, since, until);
            default -> ledgerMapper.selectStatsByBearer(tenantId, since, until);
        };
        List<StatsRow> out = new ArrayList<>(rows.size());
        for (Map<String, Object> r : rows) {
            out.add(new StatsRow(
                    String.valueOf(num(r.get("keyId"))),
                    String.valueOf(r.getOrDefault("name", "")),
                    r.get("ownerType") == null ? null : String.valueOf(r.get("ownerType")),
                    toCompanyCharged(r.get("companyCharged")),
                    num(r.get("tokens")),
                    num(r.get("calls")),
                    (int) Math.max(0L, num(r.get("members")))));
        }
        Map<String, Object> s = ledgerMapper.selectChargedSplit(tenantId, since, until);
        ChargedSplit split = new ChargedSplit(num(s.get("companyTokens")), num(s.get("personalTokens")),
                num(s.get("unmarkedTokens")), num(s.get("totalTokens")), num(s.get("calls")));
        return new StatsView(dim == null ? "bearer" : dim.trim().toLowerCase(java.util.Locale.ROOT),
                null, since, until, out, split);
    }

    /**
     * 作为<b>付费人</b>看到的账本（邀请者看被邀请人的消耗）。
     *
     * <p>与 {@link #ledgerTop}（使用者视角）是两份口径，互不替代：
     * 「谁用了」回答不了「我替谁付了多少」。</p>
     */
    public List<LedgerRow> ledgerByCharge(Long tenantId, Long chargeUserId, int limit) {
        List<TokenLedger> list = ledgerMapper.selectList(new LambdaQueryWrapper<TokenLedger>()
                .eq(TokenLedger::getTenantId, tenantId)
                .eq(TokenLedger::getChargeUserId, chargeUserId)
                .orderByDesc(TokenLedger::getCreatedAt)
                .last("limit " + Math.max(1, Math.min(limit, 200))));
        return list.stream().map(LedgerRow::from).toList();
    }

    /** -1 是 SQL 里的「未标注」哨兵值，转成 null 表示未标注。 */
    private static Integer toCompanyCharged(Object v) {
        if (v == null) {
            return null;
        }
        try {
            long n = ((Number) v).longValue();
            return n < 0 ? null : (int) n;
        } catch (RuntimeException e) {
            return null;
        }
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

    /** SQL 聚合列 → long：兼容 Integer/Long/BigDecimal/String 四种驱动返回形态。 */
    private static long num(Object v) {
        if (v == null) {
            return 0L;
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(v).trim());
        } catch (RuntimeException e) {
            return 0L;
        }
    }
}
