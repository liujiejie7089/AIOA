package cn.aioa.gitee.config;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.StringUtils;

import java.util.Arrays;

/**
 * Gitea 集成模块装配：注册 {@link GiteaProperties} + 启动期接线自检。
 *
 * <p>自检存在的理由与 {@code GiteeConfig} 相同：Gitea 的错误配置往往<b>不报错</b>，
 * 只表现为功能静默失效（授权成功但权限不足、Webhook 建好但不回调）。
 * 把这类问题在启动日志里一次说清，比等它以「Webhook 怎么不触发」的形式出现要好得多。</p>
 *
 * <p><b>为什么读的是 {@link RepoProviderSettings} 端口而不是原始 {@link GiteaProperties}</b>
 * （2026-10-10 改）：enabled / scope / oauth-authorize-base-url / org 现在可在管理端
 * 「仓库配置」页覆盖。直接读原始 bean 会打印<b>环境变量值</b>，而实际生效的是覆盖值 ——
 * 「日志说 A、行为是 B」比不打日志更误导。走端口（唯一决策点）保证展示与事实同源，
 * 与 {@code GiteeConfig} 的处理一致；不可覆盖项（base-url / TLS / 超时）仍取原始 bean。</p>
 *
 * <p>刻意只告警、不中断：配置缺项的后果是「部分能力不可用」，不是「服务不可用」。</p>
 */
@Slf4j
@Configuration
@RequiredArgsConstructor
@EnableConfigurationProperties(GiteaProperties.class)
public class GiteaConfig {

    /** 建仓与读写文件所必需的 scope。 */
    private static final String SCOPE_REPO = "repo";

    private final GiteaProperties props;
    /** 可覆盖字段的唯一决策点（管理端覆盖层 → 回落环境变量）。 */
    private final RepoProviderSettings settings;

    /** 当前选中的托管方（{@code aioa.repo.provider}），用于判断本配置是否真正生效。 */
    @Value("${aioa.repo.provider:gitee}")
    private String provider;

    @PostConstruct
    public void selfCheck() {
        if (!settings.isEnabled()) {
            // 未启用时不刷屏；但仍然提示一下「provider 选了 gitea 却没开开关」这种矛盾配置
            if (isGiteaSelected()) {
                log.warn("[gitea] provider 已选为 gitea，但 aioa.gitea.enabled=false："
                        + "所有 Gitea 接口都会返回明确错误。请检查 AIOA_GITEA_ENABLED 或「仓库配置」页。");
            }
            return;
        }

        log.info("[gitea] 接线：provider={} api={} 授权跳转={}{} scope=\"{}\" org=\"{}\" TLS={}",
                isGiteaSelected() ? "gitea(生效)" : "gitee(默认，本配置未生效)",
                props.getBaseUrl(),
                settings.getOauthAuthorizeBaseUrl(),
                props.isInsecureSkipVerify() ? "  ⚠ TLS 校验已关闭" : "",
                settings.getScope(),
                StringUtils.hasText(settings.getOrg()) ? settings.getOrg() : "(空 → 建在用户名下)",
                tlsSummary());

        checkScope(SCOPE_REPO, "建仓与读写文件将被拒");
        checkBaseUrl();
    }

    /** 校验 scope 含 repo；缺失时告警（不中断启动）。 */
    private void checkScope(String required, String impact) {
        String scope = settings.getScope() == null ? "" : settings.getScope().trim();
        if (!Arrays.asList(scope.split("\\s+")).contains(required)) {
            log.warn("[gitea] ⚠ scope 缺少「{}」：{}。Gitea 的 scope 词表与 Gitee 完全不同"
                            + "（Gitee 用 projects/hook），照抄 Gitee 的 scope 不会报错、"
                            + "只会「授权成功但权限不足」。请检查 aioa.gitea.scope。",
                    required, impact);
        }
    }

    /**
     * 校验 API 基址是否带 {@code /api/v1}。
     *
     * <p>这是换托管方时最容易漏的一步：Gitee 的实现里 {@code base-url} 已经包含
     * {@code /api/v5}，照抄习惯会写成 {@code http://host:3000}，于是所有请求打到
     * 网页根路径、返回 HTML 而非 JSON —— 错误表现为「接口不存在」，与权限问题难区分。
     * 这里提前点名。</p>
     */
    private void checkBaseUrl() {
        String base = props.getBaseUrl() == null ? "" : props.getBaseUrl().trim();
        if (!StringUtils.hasText(base)) {
            log.warn("[gitea] ⚠ aioa.gitea.base-url 为空：所有 Gitea 调用都会失败。"
                    + "示例：http://172.16.8.249:3000/api/v1");
            return;
        }
        if (!base.contains("/api/v1")) {
            log.warn("[gitea] ⚠ aioa.gitea.base-url=\"{}\" 未包含 /api/v1："
                    + "Gitea 的 REST 接口都在 /api/v1 下，缺了它会打到网页路径并拿到 HTML。"
                    + "应形如 {}/api/v1。", base, base);
        }
    }

    private String tlsSummary() {
        if (props.isInsecureSkipVerify()) {
            return "跳过校验（⚠ 不安全，仅限拿不到自签 CA 的场景）";
        }
        if (StringUtils.hasText(props.getTrustStore())) {
            return "自定义信任库 " + props.getTrustStore();
        }
        return "JVM 默认信任库";
    }

    private boolean isGiteaSelected() {
        return "gitea".equalsIgnoreCase(provider == null ? "" : provider.trim());
    }
}
