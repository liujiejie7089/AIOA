package cn.aioa.gitee.config;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.util.List;

/**
 * Gitee 集成模块装配。
 *
 * <p>只做两件事：把 {@link GiteeProperties} 注册成 Bean；启动时做一次接线自检
 * （见 {@link #selfCheck()}）。组件扫描与 Mapper 扫描由启动类统一负责
 * （{@code @SpringBootApplication(scanBasePackages="cn.aioa")} +
 * {@code @MapperScan("cn.aioa.**.mapper")}），此处重复声明只会造成扫描重复。</p>
 */
@Slf4j
@Configuration
@RequiredArgsConstructor
@EnableConfigurationProperties(GiteeProperties.class)
public class GiteeConfig {

    /** 建立仓库 / 读写文件所必需的 scope。 */
    private static final String SCOPE_PROJECTS = "projects";

    /** 配置 Webhook 所必需的 scope（**独立于 projects**，二者不可互相替代）。 */
    private static final String SCOPE_HOOK = "hook";

    private final GiteeProperties props;

    /**
     * 启动期接线自检。
     *
     * <p><b>为什么需要</b>：Gitee 接线的错误配置往往<b>不报错</b>，只表现为功能静默失效。
     * 最典型的是 scope 少了 {@code hook} —— 本地桩不校验 scope，于是回归套件全绿；
     * 接真站后建仓成功、Webhook 却被拒，且失败点（配 Webhook）离配置点（scope）很远。
     * 把这类问题在启动日志里一次说清，比等它以「Webhook 怎么不触发」的形式在生产上出现
     * 要好得多。</p>
     *
     * <p>刻意只告警、不中断：scope 缺项的后果是「部分能力不可用」，而不是「服务不可用」，
     * 为它拒绝启动反而会把可诊断的问题变成起不来。</p>
     */
    @PostConstruct
    public void selfCheck() {
        log.info("[gitee] 接线：enabled={} api={} 授权跳转={}{} scope=\"{}\"",
                props.isEnabled(), props.getBaseUrl(), props.getOauthAuthorizeBaseUrl(),
                isSandboxAuthorize()
                        ? "  ⚠ 非 gitee.com（端到端回归接线，用户到不了真实 Gitee）"
                        : "",
                props.getScope());

        if (!props.isEnabled()) {
            return;
        }
        checkScope(SCOPE_PROJECTS, "建仓与读写文件将被拒");
        checkScope(SCOPE_HOOK, "Webhook 配置将被拒（建仓仍会成功，故障点与配置点相距很远）");
    }

    /** 校验 scope 含某个必需项；缺失时告警（不中断启动）。 */
    private void checkScope(String required, String impact) {
        String scope = props.getScope() == null ? "" : props.getScope().trim();
        if (!List.of(scope.split("\\s+")).contains(required)) {
            log.warn("[gitee] ⚠ scope 缺少「{}」：{}。"
                            + "Gitee 的 {} 是独立 scope，不会被其他 scope 顺带授予；"
                            + "本地桩不校验 scope，故回归套件测不出来。"
                            + "请检查 aioa.gitee.scope / AIOA_GITEE_SCOPE。",
                    required, impact, required);
        }
    }

    /** 授权跳转是否指向本地桩（非真实 gitee.com）。 */
    private boolean isSandboxAuthorize() {
        String base = props.getOauthAuthorizeBaseUrl();
        return base != null && !base.contains("gitee.com");
    }
}
