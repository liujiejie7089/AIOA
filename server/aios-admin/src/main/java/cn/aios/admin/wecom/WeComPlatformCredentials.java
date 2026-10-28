package cn.aios.admin.wecom;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 平台级企业微信应用凭据（{@code aios.connector.wechat-work.*}，与 resource 侧
 * ConnectorProperties 同前缀同字段）。租户级 {@code connector_tenant_config} 缺位时回退这里。
 */
@Component
@ConfigurationProperties(prefix = "aios.connector.wechat-work")
@Data
public class WeComPlatformCredentials {
    private String corpId = "";
    private String agentId = "";
    private String corpSecret = "";
}
