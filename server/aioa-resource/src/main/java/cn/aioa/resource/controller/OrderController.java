package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.PaymentOrder;
import cn.aioa.resource.entity.QuotaPackage;
import cn.aioa.resource.service.OrderService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 词元包购买与支付（FR-G4 / FR-G6）：
 *   GET  /api/v1/packages                    —— 上架商品列表
 *   POST /api/v1/orders                      —— 下单（返回支付凭据/模拟收银台地址）
 *   GET  /api/v1/orders/{orderNo}            —— 订单状态查询
 *   POST /api/v1/payments/notify/mock/{no}   —— 模拟支付回调（替代微信回调，验签防重放）
 * 微信支付二期接入：新增真实回调入口 POST /payments/notify/wechat，走同一 handleNotify。
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;

    @GetMapping("/packages")
    public ApiResponse<List<QuotaPackage>> packages() {
        return ApiResponse.ok(orderService.listPackages());
    }

    @PostMapping("/orders")
    public ApiResponse<Map<String, Object>> createOrder(@RequestBody CreateOrderReq req) {
        AuthUser user = AuthUserContext.require();
        if (req == null || req.packageId() == null) {
            return ApiResponse.fail(400, "packageId 不能为空");
        }
        return ApiResponse.ok(orderService.createOrder(
                user.getTenantId(), user.getUserId(), req.packageId()));
    }

    @GetMapping("/orders/{orderNo}")
    public ApiResponse<Map<String, Object>> order(@PathVariable String orderNo) {
        AuthUser user = AuthUserContext.require();
        PaymentOrder order = orderService.findOrder(orderNo);
        if (!order.getUserId().equals(user.getUserId())) {
            return ApiResponse.fail(403, "无权查看该订单");
        }
        return ApiResponse.ok(orderService.orderView(order));
    }

    /** 模拟支付回调：演示链路中由前端「去支付」按钮调用，效果等同微信支付成功通知。 */
    @PostMapping("/payments/notify/mock/{orderNo}")
    public ApiResponse<Map<String, Object>> mockNotify(@PathVariable String orderNo,
                                                       @RequestBody(required = false) String body) {
        long tokens = orderService.handleNotify("MOCK", orderNo,
                body == null ? "" : body, null);
        return ApiResponse.ok(Map.of("orderNo", orderNo, "tokensCredited", tokens));
    }

    public record CreateOrderReq(Long packageId) {
    }
}
