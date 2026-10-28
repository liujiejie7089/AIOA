package cn.aios.admin.wecom;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 企微 OAuth 静默登录配置（{@code aios.wecom-login.*}）。
 *
 * <p>应用凭据（corpId/agentId/corpSecret）<b>不在这里</b>——复用连接器租户级配置
 * （{@code connector_tenant_config.secret_json}，管理端「连接器配置」页维护，
 * 见 ConnectorTenantConfigService），用户与管理员都不需要重复填写。</p>
 */
@Component
@ConfigurationProperties(prefix = "aios.wecom-login")
@Data
public class WeComLoginProperties {

    /** 回调公网基址（如 https://aios.example.com）；为空回退 Origin，再回退 aios.connector.public-base。 */
    private String publicBase = "";
}
