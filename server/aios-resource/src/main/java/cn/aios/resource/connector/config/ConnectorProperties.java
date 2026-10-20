package cn.aios.resource.connector.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 连接器配置（{@code aios.connector.*}，docs/58 §5/§6）。
 *
 * <p><b>secret-key</b> 由 {@code cn.aios.common.crypto.SecretCodec} 独立绑定（同一前缀），
 * 本类只承载「公网基址」与「企业微信平台级应用配置」。</p>
 *
 * <p>企业微信应用凭据有两级来源：租户级 {@code connector_tenant_config.secret_json}（优先，
 * 由管理员配置）覆盖平台级 {@code aios.connector.wechat-work.*}。租户级配置缺位时回退平台级。</p>
 */
@Component
@ConfigurationProperties(prefix = "aios.connector")
@Data
public class ConnectorProperties {

    /** OAuth2 回调公网基址；为空则回退到发起授权请求的 Origin。 */
    private String publicBase = "";

    /** 企业微信自建应用配置（平台级）。 */
    private WeChatWork wechatWork = new WeChatWork();

    @Data
    public static class WeChatWork {
        private String corpId = "";
        private String agentId = "";
        private String corpSecret = "";
    }
}
