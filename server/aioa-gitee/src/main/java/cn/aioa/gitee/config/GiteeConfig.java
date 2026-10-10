package cn.aioa.gitee.config;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.util.List;

/**
 * Gitee 集成模块装配：把 {@link GiteeProperties} 注册成 Bean，并提供接线自检的**纯判定方法**。
 *
 * <p>组件扫描与 Mapper 扫描由启动类统一负责
 * （{@code @SpringBootApplication(scanBasePackages="cn.aioa")} +
 * {@code @MapperScan("cn.aioa.**.mapper")}），此处重复声明只会造成扫描重复。</p>
 *
 * <p><b>为什么自检不再由本类的 {@code @PostConstruct} 触发</b>（2026-10-10 改）：
 * 接线值现在可以来自管理端（表 {@code gitee_platform_config}），而覆盖层是在
 * {@code GiteePlatformConfigService} 里加载的。若仍在 {@code @PostConstruct} 打印，
 * 打印的是<b>环境变量值</b>而非生效值——于是启动日志与实际行为不一致，
 * 这类「日志说 A、行为是 B」比不打日志更误导。故本类只留判定方法，
 * 由持有生效值的 {@code GiteePlatformConfigService} 在加载完成后调用（展示与事实同源）。</p>
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

    /**
     * scope 自检：缺 {@code projects} / {@code hook} 时告警。
     *
     * <p><b>为什么需要</b>：Gitee 接线的错误配置往往<b>不报错</b>，只表现为功能静默失效。
     * 最典型的是 scope 少了 {@code hook} —— 本地桩不校验 scope，于是回归套件全绿；
     * 接真站后建仓成功、Webhook 却被拒，且失败点（配 Webhook）离配置点（scope）很远。
     * 把这类问题在日志里一次说清，比等它以「Webhook 怎么不触发」的形式在生产上出现要好得多。</p>
     *
     * <p>刻意只告警、不中断：scope 缺项的后果是「部分能力不可用」而不是「服务不可用」，
     * 为它拒绝启动反而会把可诊断的问题变成起不来。</p>
     *
     * @param enabled       生效的平台开关；关闭时不做检查
     * @param effectiveScope 生效的 scope（可能来自管理端）
     */
    public void checkScope(boolean enabled, String effectiveScope) {
        if (!enabled) {
            return;
        }
        checkOne(effectiveScope, SCOPE_PROJECTS, "建仓与读写文件将被拒");
        checkOne(effectiveScope, SCOPE_HOOK, "Webhook 配置将被拒（建仓仍会成功，故障点与配置点相距很远）");
    }

    /** 校验 scope 含某个必需项；缺失时告警（不中断启动）。 */
    private void checkOne(String scopeValue, String required, String impact) {
        String scope = scopeValue == null ? "" : scopeValue.trim();
        if (!List.of(scope.split("\\s+")).contains(required)) {
            log.warn("[gitee] ⚠ scope 缺少「{}」：{}。"
                            + "Gitee 的 {} 是独立 scope，不会被其他 scope 顺带授予；"
                            + "本地桩不校验 scope，故回归套件测不出来。"
                            + "请检查「仓库配置」页或 aioa.gitee.scope / AIOA_GITEE_SCOPE。",
                    required, impact, required);
        }
    }

    /**
     * 授权跳转是否指向本地桩（非真实 gitee.com）。
     *
     * <p>注意不能写成「含 {@code gitee.com} 即真实」的简单否定——必须由调用方知道
     * 当前托管方；此处只按 Gitee 公有云口径判定，Gitea 自建实例请走适配器的
     * {@code authorizeHostIsSandbox()}。</p>
     */
    public boolean isSandboxAuthorize(String authorizeBaseUrl) {
        return authorizeBaseUrl == null || !authorizeBaseUrl.contains("gitee.com");
    }
}
