package cn.aioa.integration.scfy;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * scfy 接入配置。
 *
 * <p><b>默认 enabled=false</b>。这是「可插拔」的落点：不给配置就等于没接入 ——
 * 不会注册任何工具、不会建任何连接、不会出现在模型的能力清单里。
 * 想启用必须显式打开，避免「拷了代码就自动对外暴露一个外部系统」。</p>
 *
 * <p><b>为什么 baseUrl 默认指向生产</b>：2026-09-23 实测四套环境只有生产西昌可达
 * （本地 502 / 测试内网不可达 / 自贡 404）。默认值必须写成实际能用的那个，
 * 否则「默认配置 = 一跑就报错」，使用者会以为接入代码坏了。
 * 测试环境就绪后由配置覆盖，不需改代码。</p>
 */
@ConfigurationProperties(prefix = "aioa.integration.scfy")
public class ScfyIntegrationProperties {

    /** 总开关。false 时整个模块不产生任何 Bean/工具。 */
    private boolean enabled = false;

    /** 服务基址（含上下文路径 /scfy）。 */
    private String baseUrl = "https://szbhpt.tsichuan.com/scfy";

    /** 连接超时（毫秒）。 */
    private int connectTimeoutMs = 5000;

    /** 读取超时（毫秒）。大屏接口首访可能触发缓存回源，给足余量。 */
    private int readTimeoutMs = 15000;

    /** 单次响应最大字节数，超出即截断并标记 —— 防止一个接口返回几十 MB 撑爆上下文。 */
    private int maxBytes = 512 * 1024;

    /** 幂等 GET 的重试次数（含首次）。仅在网络异常/5xx 时重试。 */
    private int maxAttempts = 2;

    /** 重试退避基数（毫秒），第 n 次退避 = base * 2^(n-1)。 */
    private long retryBackoffMs = 300;

    /**
     * 是否启用「需登录」能力。
     * <p>当前阶段业务约束是<b>只读查询</b>，而所有 /show/* 接口都无需登录，
     * 因此默认关闭。置 true 时必须同时提供 username/password，
     * 否则启动即失败（不允许「静默降级成匿名」—— 那会让需登录接口以 401 形式
     * 伪装成「无数据」）。</p>
     */
    private boolean loginEnabled = false;

    /** 登录用户名（仅 loginEnabled=true 时需要）。 */
    private String username;

    /** 登录密码明文 —— 适配器内部用 AES/ECB/PKCS5Padding 加密后提交。 */
    private String password;

    /** 是否校验 TLS 证书。默认校验；仅在本机信任库缺链时临时置 false。 */
    private boolean verifySsl = true;

    /** 缓存：大屏数据有分钟级延迟，同参数短时间重复调用可直接复用。 */
    private int cacheTtlSeconds = 0;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    public int getConnectTimeoutMs() {
        return connectTimeoutMs;
    }

    public void setConnectTimeoutMs(int connectTimeoutMs) {
        this.connectTimeoutMs = connectTimeoutMs;
    }

    public int getReadTimeoutMs() {
        return readTimeoutMs;
    }

    public void setReadTimeoutMs(int readTimeoutMs) {
        this.readTimeoutMs = readTimeoutMs;
    }

    public int getMaxBytes() {
        return maxBytes;
    }

    public void setMaxBytes(int maxBytes) {
        this.maxBytes = maxBytes;
    }

    public int getMaxAttempts() {
        return maxAttempts;
    }

    public void setMaxAttempts(int maxAttempts) {
        this.maxAttempts = maxAttempts;
    }

    public long getRetryBackoffMs() {
        return retryBackoffMs;
    }

    public void setRetryBackoffMs(long retryBackoffMs) {
        this.retryBackoffMs = retryBackoffMs;
    }

    public boolean isLoginEnabled() {
        return loginEnabled;
    }

    public void setLoginEnabled(boolean loginEnabled) {
        this.loginEnabled = loginEnabled;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    public boolean isVerifySsl() {
        return verifySsl;
    }

    public void setVerifySsl(boolean verifySsl) {
        this.verifySsl = verifySsl;
    }

    public int getCacheTtlSeconds() {
        return cacheTtlSeconds;
    }

    public void setCacheTtlSeconds(int cacheTtlSeconds) {
        this.cacheTtlSeconds = cacheTtlSeconds;
    }
}
