package cn.aios.resource.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.service.BillingService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 词元额度与用量账单。
 * GET /api/v1/quota            —— 额度条（FR-G6 额度用尽三分支的数据源）
 * GET /api/v1/ledger?limit=50  —— 账本流水，与平台账本一致、明细可导出对账
 * GET /api/v1/billing/stats    —— 归属统计（按账号 / 按使用者 / 按付费人，docs/71 §7）
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class BillingController {

    private final BillingService billingService;

    @GetMapping("/quota")
    public ApiResponse<BillingService.QuotaView> quota() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(billingService.current(user.getTenantId(), user.getUserId()));
    }

    @GetMapping("/ledger")
    public ApiResponse<List<BillingService.LedgerRow>> ledger(
            @RequestParam(name = "limit", defaultValue = "50") int limit,
            @RequestParam(name = "scope", required = false) String scope) {
        AuthUser user = AuthUserContext.require();
        // scope=charge 是「作为付费人看账本」（邀请者看被邀请人的消耗）；
        // 缺省仍是「作为使用者看账本」。两份口径互不替代，回答的是不同问题。
        if ("charge".equalsIgnoreCase(scope)) {
            return ApiResponse.ok(billingService.ledgerByCharge(
                    user.getTenantId() == null ? 0L : user.getTenantId(), user.getUserId(), limit));
        }
        return ApiResponse.ok(billingService.ledgerTop(user.getTenantId(), user.getUserId(), limit));
    }

    /**
     * 归属统计。dim=credential 按账号 / bearer 按使用者 / charge 按付费人。
     *
     * <p>period 形如 {@code 2026-11}，用半开区间 {@code [月初, 次月初)}，
     * 免得「月末 23:59:59 之后、次月 0 点之前」的记录被重复计入两个月。</p>
     *
     * <p>租户作用域：取登录账号自身租户 —— 统计的是「本租户的账本」，
     * 不做跨租户汇总（那是平台级运营口径，另走管理端接口）。</p>
     */
    @GetMapping("/billing/stats")
    public ApiResponse<BillingService.StatsView> stats(
            @RequestParam(name = "dim", defaultValue = "bearer") String dim,
            @RequestParam(name = "period", required = false) String period) {
        AuthUser user = AuthUserContext.require();
        LocalDateTime[] window = periodWindow(period);
        return ApiResponse.ok(billingService.stats(
                user.getTenantId() == null ? 0L : user.getTenantId(), dim, window[0], window[1]));
    }

    /** period → 半开区间 [月初, 次月初)。缺省或非法时回退当月。 */
    private static LocalDateTime[] periodWindow(String period) {
        java.time.YearMonth ym;
        try {
            ym = java.time.YearMonth.parse(String.valueOf(period).trim());
        } catch (RuntimeException e) {
            ym = java.time.YearMonth.now();
        }
        return new LocalDateTime[]{ym.atDay(1).atStartOfDay(), ym.plusMonths(1).atDay(1).atStartOfDay()};
    }
}
