package cn.aios.common.security;

import cn.aios.common.exception.BizException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * H-2 SSRF 共用 host 守卫（纯逻辑，无 Spring）。
 *
 * <p>唯一判定点 = {@link UrlHostGuard}；生产默认拒私有地址，本地 E2E 通过
 * {@code allowPrivateHosts=true} 放行 {@code http://127.0.0.1:8090} 桩。</p>
 */
class UrlHostGuardTest {

    @Test
    @DisplayName("allow-private=true 放行 127.0.0.1:8090（本地 E2E 桩）")
    void allowsStubWhenPrivateAllowed() {
        assertDoesNotThrow(() -> UrlHostGuard.assertAllowed("http://127.0.0.1:8090/api", true));
    }

    @Test
    @DisplayName("allow-private=false 拒绝 127.0.0.1（含端口）")
    void rejectsLoopbackWhenPrivateBlocked() {
        BizException e = assertThrows(BizException.class,
                () -> UrlHostGuard.assertAllowed("http://127.0.0.1:8090/api", false));
        assertEquals(403, e.getCode());
    }

    @Test
    @DisplayName("169.254.169.254 在 allow-private=true 下仍拒绝（云元数据）")
    void metadataBlockedEvenWhenPrivateAllowed() {
        BizException e = assertThrows(BizException.class,
                () -> UrlHostGuard.assertAllowed("http://169.254.169.254/latest/meta-data", true));
        assertEquals(403, e.getCode());
    }

    @Test
    @DisplayName("169.254.169.254 在 allow-private=false 下也拒绝")
    void metadataBlockedWhenPrivateBlocked() {
        BizException e = assertThrows(BizException.class,
                () -> UrlHostGuard.assertAllowed("http://169.254.169.254/latest/meta-data", false));
        assertEquals(403, e.getCode());
    }

    @Test
    @DisplayName("file:// 协议被拒绝（非 http/https）")
    void rejectsFileScheme() {
        BizException e = assertThrows(BizException.class,
                () -> UrlHostGuard.assertAllowed("file:///etc/passwd", true));
        assertEquals(400, e.getCode());
    }

    @Test
    @DisplayName("公开域名在两种开关下都放行")
    void allowsPublicHost() {
        assertDoesNotThrow(() -> UrlHostGuard.assertAllowed("https://api.example.com/v1/x", false));
        assertDoesNotThrow(() -> UrlHostGuard.assertAllowed("https://api.example.com/v1/x", true));
    }

    @Test
    @DisplayName("RFC1918（10.0.0.5）在 false 下拒绝、true 下放行")
    void rfc1918BlockedUnlessAllowed() {
        assertThrows(BizException.class, () -> UrlHostGuard.assertAllowed("http://10.0.0.5:9000", false));
        assertDoesNotThrow(() -> UrlHostGuard.assertAllowed("http://10.0.0.5:9000", true));
    }

    @Test
    @DisplayName("localhost 在 false 下拒绝、true 下放行")
    void localhostBlockedUnlessAllowed() {
        assertThrows(BizException.class, () -> UrlHostGuard.assertAllowed("http://localhost:8080", false));
        assertDoesNotThrow(() -> UrlHostGuard.assertAllowed("http://localhost:8080", true));
    }

    @Test
    @DisplayName("0.0.0.0 视为私有地址，false 下拒绝")
    void zeroAddressBlocked() {
        assertThrows(BizException.class, () -> UrlHostGuard.assertAllowed("http://0.0.0.0:8080", false));
    }

    @Test
    @DisplayName("resolveAllowPrivate：未配置随 profile（prod=false / 其它=true），配置优先")
    void resolveAllowPrivateSemantics() {
        assertEquals(false, UrlHostGuard.resolveAllowPrivate(null, true));
        assertEquals(true, UrlHostGuard.resolveAllowPrivate(null, false));
        assertEquals(true, UrlHostGuard.resolveAllowPrivate(true, true));   // 环境变量可覆盖 prod
        assertEquals(false, UrlHostGuard.resolveAllowPrivate(false, false));
    }
}
