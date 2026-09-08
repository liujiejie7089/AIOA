package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.service.BillingService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 词元额度与用量账单。
 * GET /api/v1/quota            —— 额度条（FR-G6 额度用尽三分支的数据源）
 * GET /api/v1/ledger?limit=50  —— 账本流水，与平台账本一致、明细可导出对账
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
            @RequestParam(name = "limit", defaultValue = "50") int limit) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(billingService.ledgerTop(user.getTenantId(), user.getUserId(), limit));
    }
}
