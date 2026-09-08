package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.PaymentOrder;
import cn.aioa.resource.entity.QuotaPackage;
import cn.aioa.resource.mapper.PaymentOrderMapper;
import cn.aioa.resource.mapper.QuotaPackageMapper;
import cn.aioa.resource.service.payment.PaymentChannel;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 词元包订单与支付（FR-G4：商品列表 → 下单 → 支付 → 额度实时到账 → 订单可查）。
 *
 * 闭环要求（需求 3.7）：额度用尽 → 购买 → 到账全链路自动完成，无人工干预。
 * 一期用 MOCK 通道演示（createPayment 直接给出模拟收银台地址），
 * 微信支付二期接入：实现 PaymentChannel 即可，订单/到账逻辑零改动。
 * 幂等：回调以订单状态机（PENDING→PAID 单向）防重放，重复通知不重复到账。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService {

    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");

    private final QuotaPackageMapper packageMapper;
    private final PaymentOrderMapper orderMapper;
    private final BillingService billingService;
    private final ActivityLogService activityLogService;
    private final Map<String, PaymentChannel> channels;

    /** 上架中的商品列表（FR-G6 购买入口数据源）。 */
    public List<QuotaPackage> listPackages() {
        return packageMapper.selectList(new LambdaQueryWrapper<QuotaPackage>()
                .eq(QuotaPackage::getStatus, QuotaPackage.STATUS_ONSALE)
                .orderByAsc(QuotaPackage::getSort));
    }

    /** 下单：生成 PENDING 订单并返回支付凭据（模拟通道返回模拟收银台地址）。 */
    public Map<String, Object> createOrder(Long tenantId, Long userId, Long packageId) {
        QuotaPackage pkg = packageMapper.selectById(packageId);
        if (pkg == null || !QuotaPackage.STATUS_ONSALE.equals(pkg.getStatus())) {
            throw BizException.notFound("商品不存在或已下架");
        }
        PaymentOrder order = new PaymentOrder();
        order.setOrderNo(newOrderNo());
        order.setTenantId(tenantId == null ? 0L : tenantId);
        order.setUserId(userId);
        order.setPackageId(pkg.getId());
        order.setPackageName(pkg.getPackageName());
        order.setTokens(pkg.getTokens());
        order.setAmountCents(pkg.getPriceCents());
        order.setStatus(PaymentOrder.STATUS_PENDING);
        order.setCreatedAt(LocalDateTime.now());
        order.setCreatedBy(userId);
        orderMapper.insert(order);

        PaymentChannel channel = channels.get("mockPaymentChannel");
        Map<String, Object> payParams = new java.util.LinkedHashMap<>(channel.createPayment(order.getOrderNo(),
                order.getAmountCents(), pkg.getPackageName()));
        activityLogService.record(order.getTenantId(), userId,
                "购买词元包（" + pkg.getPackageName() + "，下单）", "ok", "订单 " + order.getOrderNo());
        payParams.put("orderNo", order.getOrderNo());
        return payParams;
    }

    public PaymentOrder findOrder(String orderNo) {
        PaymentOrder order = orderMapper.selectOne(new LambdaQueryWrapper<PaymentOrder>()
                .eq(PaymentOrder::getOrderNo, orderNo));
        if (order == null) {
            throw BizException.notFound("订单不存在：" + orderNo);
        }
        return order;
    }

    /**
     * 支付回调（验签 + 防重放）：将订单置 PAID 并实时到账（free_tokens += tokens）。
     * 幂等：订单已 PAID 时直接返回，不重复到账。
     *
     * @return 到账词元数（重复通知返回 0）
     */
    @Transactional(rollbackFor = Exception.class)
    public long handleNotify(String channelCode, String orderNo, String body, String signature) {
        PaymentChannel channel = channels.get(channelKey(channelCode));
        if (channel == null) {
            throw BizException.badRequest("未知支付通道：" + channelCode);
        }
        if (!channel.verifyNotify(orderNo, body, signature)) {
            throw BizException.forbidden("支付回调验签失败");
        }
        PaymentOrder order = findOrder(orderNo);
        if (PaymentOrder.STATUS_PAID.equals(order.getStatus())) {
            log.info("order {} already paid, notify ignored (replay-safe)", orderNo);
            return 0;
        }
        if (!PaymentOrder.STATUS_PENDING.equals(order.getStatus())) {
            throw BizException.badRequest("订单状态不可支付：" + order.getStatus());
        }
        PaymentOrder patch = new PaymentOrder();
        patch.setId(order.getId());
        patch.setStatus(PaymentOrder.STATUS_PAID);
        patch.setPayChannel(channelCode);
        patch.setPayTime(LocalDateTime.now());
        patch.setUpdatedAt(LocalDateTime.now());
        orderMapper.updateById(patch);

        // 额度实时到账（个人额度行；无个人行时 getOrCreate 会建/回落共享行）
        billingService.addFreeTokens(order.getTenantId(), order.getUserId(), order.getTokens());
        activityLogService.record(order.getTenantId(), order.getUserId(),
                "购买词元包（" + order.getPackageName() + "，到账）", "ok",
                "+" + order.getTokens() + " 词元");
        log.info("order {} paid via {}: +{} tokens", orderNo, channelCode, order.getTokens());
        return order.getTokens();
    }

    /** 订单状态视图（FR-G4 订单状态可查）。 */
    public Map<String, Object> orderView(PaymentOrder o) {
        return Map.of(
                "orderNo", o.getOrderNo(),
                "packageName", o.getPackageName(),
                "tokens", o.getTokens(),
                "amountCents", o.getAmountCents(),
                "status", o.getStatus(),
                "payChannel", o.getPayChannel() == null ? "" : o.getPayChannel(),
                "payTime", o.getPayTime() == null ? "" : o.getPayTime().toString(),
                "createdAt", o.getCreatedAt().toString());
    }

    private static String newOrderNo() {
        String random = String.format("%06d", new Random().nextInt(1_000_000));
        return "ORD" + LocalDateTime.now().format(TS) + random;
    }

    /** Spring 注入的 bean 名（mockPaymentChannel / wechatPaymentChannel）。 */
    private static String channelKey(String code) {
        return code == null ? "" : code.toLowerCase() + "PaymentChannel";
    }
}
