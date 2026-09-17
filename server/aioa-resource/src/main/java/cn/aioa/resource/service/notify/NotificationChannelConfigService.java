package cn.aioa.resource.service.notify;

import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.NotificationChannelConfig;
import cn.aioa.resource.mapper.NotificationChannelConfigMapper;
import cn.aioa.resource.mapper.SysUserLiteMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 通知通道配置服务：列表 / 保存 / 测试。
 *
 * <p>通道码 → 标签：INAPP=站内信、EMAIL=邮件、SMS=短信、PUSH=移动推送。
 * 配置校验在服务端完成（不能只靠前端）：必填键缺失或 url 非法时抛
 * {@link BizException#badRequest}，message 指明是哪个键不合法并回显该值。
 * config_json 的未知键原样保留（无损往返）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationChannelConfigService {

    private static final List<String> CHANNEL_ORDER = List.of("INAPP", "EMAIL", "SMS", "PUSH");

    private static final Map<String, String> LABELS = Map.of(
            "INAPP", "站内信", "EMAIL", "邮件", "SMS", "短信", "PUSH", "移动推送");

    /** 各通道必填配置键。 */
    private static final Map<String, List<String>> REQUIRED = Map.of(
            "EMAIL", List.of("url", "token", "from"),
            "SMS", List.of("url", "token", "signName"),
            "PUSH", List.of("url", "token"));

    private final NotificationChannelConfigMapper configMapper;
    private final SysUserLiteMapper userMapper;
    private final ObjectMapper objectMapper;
    private final List<NotificationChannel> channels;

    /** 某租户全部通道视图：{code,label,enabled,configured,config}。 */
    public List<Map<String, Object>> list(Long tenantId) {
        List<NotificationChannelConfig> rows = configMapper.selectList(new LambdaQueryWrapper<NotificationChannelConfig>()
                .eq(NotificationChannelConfig::getTenantId, tenantId));
        Map<String, NotificationChannelConfig> byCode = new LinkedHashMap<>();
        for (NotificationChannelConfig r : rows) {
            byCode.putIfAbsent(r.getChannelCode(), r);
        }

        List<Map<String, Object>> items = new ArrayList<>();
        for (String code : CHANNEL_ORDER) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("code", code);
            m.put("label", LABELS.get(code));
            NotificationChannelConfig cfg = byCode.get(code);
            boolean enabled = "INAPP".equals(code)
                    || (cfg != null && cfg.getEnabled() != null && cfg.getEnabled() == 1);
            m.put("enabled", enabled);
            Map<String, Object> config = null;
            boolean configured = true;
            if (cfg != null && cfg.getConfigJson() != null) {
                config = parse(cfg.getConfigJson());
                configured = isConfigured(code, config);
            } else if (!"INAPP".equals(code)) {
                configured = false;
            }
            m.put("configured", configured);
            m.put("config", config);
            items.add(m);
        }
        return items;
    }

    /** 保存（upsert）某通道的启用开关与配置。INAPP 不可配置。 */
    public Map<String, Object> save(Long tenantId, String code, boolean enabled,
                                    Map<String, Object> config, Long actorUserId) {
        if (!LABELS.containsKey(code)) {
            throw BizException.badRequest("未知通知通道：" + code);
        }
        if ("INAPP".equals(code)) {
            throw BizException.badRequest("站内信通道恒可用，不可配置");
        }
        // 服务端强校验（即使禁用也校验所提供配置的合法性，避免存脏数据）
        validate(code, config);

        String configJson = (config == null || config.isEmpty()) ? null : writeJson(config);
        NotificationChannelConfig existing = configMapper.selectOne(new LambdaQueryWrapper<NotificationChannelConfig>()
                .eq(NotificationChannelConfig::getTenantId, tenantId)
                .eq(NotificationChannelConfig::getChannelCode, code));
        if (existing == null) {
            NotificationChannelConfig c = new NotificationChannelConfig();
            c.setTenantId(tenantId);
            c.setChannelCode(code);
            c.setEnabled(enabled ? 1 : 0);
            c.setConfigJson(configJson);
            c.setCreatedBy(actorUserId);
            c.setCreatedAt(LocalDateTime.now());
            configMapper.insert(c);
        } else {
            existing.setEnabled(enabled ? 1 : 0);
            existing.setConfigJson(configJson);
            existing.setUpdatedBy(actorUserId);
            existing.setUpdatedAt(LocalDateTime.now());
            configMapper.updateById(existing);
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("code", code);
        m.put("enabled", enabled);
        m.put("config", config);
        return m;
    }

    /**
     * 真实发出一条测试消息（同步，供界面「测试」按钮）。
     *
     * <p>INAPP 无外部调用，直接登记 SENT；其余通道按配置 POST 网关。
     * EMAIL 未提供 to 时回落到测试者本人邮箱；SMS/PUSH 当前数据模型未建模收件地址，
     * 必须显式提供 to，否则 400。</p>
     */
    public Map<String, Object> test(Long tenantId, String code, String to, Long actorUserId) {
        if (!LABELS.containsKey(code)) {
            throw BizException.badRequest("未知通知通道：" + code);
        }
        if ("INAPP".equals(code)) {
            return result(code, "SENT", "站内信无需网关，已登记成功", LocalDateTime.now());
        }
        NotificationChannelConfig cfg = configMapper.selectOne(new LambdaQueryWrapper<NotificationChannelConfig>()
                .eq(NotificationChannelConfig::getTenantId, tenantId)
                .eq(NotificationChannelConfig::getChannelCode, code));
        Map<String, Object> config = (cfg != null && cfg.getConfigJson() != null)
                ? parse(cfg.getConfigJson()) : Map.of();
        validate(code, config);

        String resolvedTo = (to == null || to.isBlank()) ? null : to.trim();
        if (resolvedTo == null && "EMAIL".equals(code)) {
            resolvedTo = lookupEmail(actorUserId);
        }
        if (resolvedTo == null) {
            throw BizException.badRequest("通道 " + code
                    + " 测试需提供收件地址 to（当前数据模型未建模手机号/设备令牌）");
        }

        DeliveryContext ctx = new DeliveryContext();
        ctx.setTenantId(tenantId);
        ctx.setUserId(actorUserId);
        ctx.setType("TEST");
        ctx.setTitle("消息中心通道测试");
        ctx.setContent("这是一条来自统一消息中心的测试消息。");
        ctx.setRefId(null);
        ctx.setConfig(config);
        ctx.setTo(resolvedTo);

        try {
            channelOf(code).send(ctx);
            return result(code, "SENT", "测试消息已发送", LocalDateTime.now());
        } catch (Exception e) {
            return result(code, "FAILED", truncate(e.getMessage(), 300), null);
        }
    }

    // ------------------------------------------------------------------ 工具

    /** 服务端配置校验：必填键缺失或 url 非法时抛 badRequest（指明键并回显值）。 */
    private void validate(String code, Map<String, Object> config) {
        if (config == null) {
            config = Map.of();
        }
        List<String> required = REQUIRED.get(code);
        if (required == null) {
            return; // INAPP 无配置
        }
        for (String key : required) {
            Object v = config.get(key);
            if (v == null || !StringUtils.hasText(String.valueOf(v).trim())) {
                throw BizException.badRequest("通道 " + code + " 缺少必填配置项：" + key);
            }
        }
        Object urlObj = config.get("url");
        if (urlObj != null) {
            String url = String.valueOf(urlObj).trim();
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                throw BizException.badRequest(
                        "通道 " + code + " 配置项 url 必须以 http:// 或 https:// 开头，当前值：" + url);
            }
        }
        Object tplObj = config.get("titleTemplate");
        if (tplObj != null) {
            String tpl = String.valueOf(tplObj);
            if (tpl.length() > 64) {
                throw BizException.badRequest(
                        "通道 PUSH 配置项 titleTemplate 长度不能超过 64，当前长度：" + tpl.length());
            }
        }
    }

    private boolean isConfigured(String code, Map<String, Object> config) {
        List<String> required = REQUIRED.get(code);
        if (required == null) {
            return true; // INAPP
        }
        for (String key : required) {
            Object v = config.get(key);
            if (v == null || !StringUtils.hasText(String.valueOf(v).trim())) {
                return false;
            }
        }
        return true;
    }

    private NotificationChannel channelOf(String code) {
        return channels.stream()
                .filter(c -> c.code().equals(code))
                .findFirst()
                .orElseThrow(() -> BizException.badRequest("未知通知通道：" + code));
    }

    private String lookupEmail(Long userId) {
        if (userId == null) {
            return null;
        }
        Map<String, Object> u = userMapper.selectLite(userId);
        if (u == null) {
            return null;
        }
        Object e = u.get("email");
        return e == null ? null : String.valueOf(e);
    }

    private Map<String, Object> parse(String json) {
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> m = objectMapper.readValue(json, Map.class);
            return m == null ? new LinkedHashMap<>() : m;
        } catch (Exception e) {
            log.warn("解析通道配置失败：{}", e.getMessage());
            return new LinkedHashMap<>();
        }
    }

    private String writeJson(Map<String, Object> config) {
        try {
            return objectMapper.writeValueAsString(config);
        } catch (Exception e) {
            throw BizException.badRequest("通道配置序列化失败：" + e.getMessage());
        }
    }

    private static Map<String, Object> result(String code, String status, String message, LocalDateTime sentAt) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("channelCode", code);
        m.put("status", status);
        m.put("message", message);
        m.put("sentAt", sentAt == null ? null : sentAt.toString());
        return m;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() > max ? s.substring(0, max) : s;
    }
}
