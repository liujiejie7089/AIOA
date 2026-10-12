package cn.aioa.common.security;

import cn.aioa.common.exception.BizException;

import java.net.URI;
import java.net.URISyntaxException;

/**
 * 共用 URL/host 守卫（H-2，铁律：同一决策点只在一处判定）。
 *
 * <p><b>唯一判定点</b>：{@code GiteePlatformConfigService.checkUrl} 与 {@code ToolDispatcher.buildUrl}
 * 都委托本类，杜绝「两处各写一套 SSRF 判定」导致的口径漂移。</p>
 *
 * <p><b>判定规则</b>：</p>
 * <ol>
 *   <li>scheme 必须是 http/https（{@code file:///etc/passwd} 之类一律拒绝）；</li>
 *   <li>host 不可为空；</li>
 *   <li>拒回环 / RFC1918 / link-local / {@code 0.0.0.0}（统称私有地址）—— <b>除非</b>
 *       显式放行（见 {@link #resolveAllowPrivate}）；</li>
 *   <li>云元数据地址 {@code 169.254.169.254} <b>永远拒绝</b>，即便私有地址已放行
 *       （避免 SSRF 打到 IMDS 偷云凭据）。</li>
 * </ol>
 *
 * <p><b>纯逻辑、无 Spring 依赖</b>，便于单元测试直接调用。</p>
 */
public final class UrlHostGuard {

    private UrlHostGuard() {
    }

    /** 云元数据地址（AWS/GCP/阿里云/腾讯云 IMDS），无论是否放行私有地址都禁止。 */
    public static final String CLOUD_METADATA_IP = "169.254.169.254";

    private enum Category {
        PUBLIC, PRIVATE, METADATA
    }

    /**
     * 解析并校验 URL 是否允许访问。非法或被禁时抛 {@link BizException}（400/403）。
     *
     * @param url               待校验地址
     * @param allowPrivateHosts 是否放行回环/RFC1918/link-local/0.0.0.0 等私有地址
     */
    public static void assertAllowed(String url, boolean allowPrivateHosts) {
        if (url == null || url.isBlank()) {
            throw BizException.badRequest("URL 不能为空");
        }
        URI uri;
        try {
            uri = new URI(url.trim());
        } catch (URISyntaxException e) {
            throw BizException.badRequest("URL 语法非法：" + url);
        }
        String scheme = uri.getScheme();
        if (scheme == null || (!"http".equalsIgnoreCase(scheme) && !"https".equalsIgnoreCase(scheme))) {
            throw BizException.badRequest("仅允许 http/https 协议，已拒绝 scheme="
                    + (scheme == null ? "(无)" : scheme) + "：" + url);
        }
        String host = uri.getHost();
        if (host == null || host.isBlank()) {
            throw BizException.badRequest("URL 缺少 host，已拒绝：" + url);
        }
        host = normalizeHost(host);
        Category cat = classify(host);
        if (cat == Category.METADATA) {
            throw BizException.forbidden("SSRF 防护：禁止访问云元数据地址 " + CLOUD_METADATA_IP
                    + "（云凭据泄露风险）：" + url);
        }
        if (cat == Category.PRIVATE && !allowPrivateHosts) {
            throw BizException.forbidden("SSRF 防护：禁止访问私有/回环地址 " + host
                    + "（本地联调请开启 aioa.security.allow-private-hosts）：" + url);
        }
    }

    /**
     * 解析「是否放行私有地址」的最终取值：显式配置优先；未配置时随 profile
     * （prod → false，其它 → true）兜底，以便本地 E2E 默认能打 {@code http://127.0.0.1:8090} 桩。
     */
    public static boolean resolveAllowPrivate(Boolean configured, boolean prodProfile) {
        if (configured != null) {
            return configured;
        }
        return !prodProfile;
    }

    private static String normalizeHost(String host) {
        String h = host.toLowerCase(java.util.Locale.ROOT);
        while (h.startsWith("[")) {
            h = h.substring(1);
        }
        while (h.endsWith("]") || h.endsWith(".")) {
            if (h.endsWith("]")) {
                h = h.substring(0, h.length() - 1);
            } else if (h.endsWith(".")) {
                h = h.substring(0, h.length() - 1);
            } else {
                break;
            }
        }
        return h;
    }

    private static Category classify(String host) {
        if (CLOUD_METADATA_IP.equals(host)) {
            return Category.METADATA;
        }
        if (isPrivateHost(host)) {
            return Category.PRIVATE;
        }
        return Category.PUBLIC;
    }

    private static boolean isPrivateHost(String host) {
        if ("localhost".equals(host) || "::1".equals(host) || "::".equals(host)) {
            return true;
        }
        if (isIpv4(host)) {
            int[] o = parseIpv4(host);
            if (o == null) {
                return false;
            }
            if (o[0] == 0) {
                return true; // 0.0.0.0（未指定地址）
            }
            if (o[0] == 127) {
                return true; // 回环 127.0.0.0/8
            }
            if (o[0] == 10) {
                return true; // RFC1918 10.0.0.0/8
            }
            if (o[0] == 172 && o[1] >= 16 && o[1] <= 31) {
                return true; // RFC1918 172.16.0.0/12
            }
            if (o[0] == 192 && o[1] == 168) {
                return true; // RFC1918 192.168.0.0/16
            }
            if (o[0] == 169 && o[1] == 254) {
                return true; // link-local 169.254.0.0/16（元数据地址已单独处理）
            }
        }
        // IPv6：链路本地 fe80::/10 与唯一本地 fc00::/7 视为私有
        if (host.indexOf(':') >= 0) {
            if (host.startsWith("fe80:") || host.startsWith("fc") || host.startsWith("fd")) {
                return true;
            }
            // ::ffff:1.2.3.4（IPv4 映射）按内嵌 IPv4 再判一次
            int idx = host.lastIndexOf(':');
            String tail = host.substring(idx + 1);
            if (isIpv4(tail)) {
                return isPrivateHost(tail);
            }
        }
        return false;
    }

    private static boolean isIpv4(String host) {
        if (host.isEmpty()) {
            return false;
        }
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) {
            return false;
        }
        for (String p : parts) {
            if (p.isEmpty() || p.length() > 3) {
                return false;
            }
            for (int i = 0; i < p.length(); i++) {
                if (!Character.isDigit(p.charAt(i))) {
                    return false;
                }
            }
            int v = Integer.parseInt(p);
            if (v < 0 || v > 255) {
                return false;
            }
        }
        return true;
    }

    private static int[] parseIpv4(String host) {
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) {
            return null;
        }
        int[] o = new int[4];
        for (int i = 0; i < 4; i++) {
            try {
                o[i] = Integer.parseInt(parts[i]);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return o;
    }
}
