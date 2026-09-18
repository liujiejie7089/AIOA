package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaConfig;
import cn.aioa.gitee.config.GiteeConfig;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.util.TestPropertyValues;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 托管方实现的**互斥装配**测试。
 *
 * <p><b>为什么必须测这一条</b>：上层 8 个服务都是按接口 {@link RepoProviderClient} 注入的。
 * 如果两个实现同时成为 Bean，容器会在启动时报
 * 「expected single matching bean but found 2」——而且是在**整个应用起不来**的层面失败，
 * 不是在某个功能上失败。反过来，如果两个都被条件排除，则是「找不到 Bean」。
 * 两种都是「配置改一下就全站不可用」的爆炸半径，因此单独守住。</p>
 *
 * <p>这里只装配两个客户端类与它们的配置类（不加载整个应用上下文、不连数据库），
 * 因此既是确定性的，也足够快。</p>
 */
class RepoProviderWiringTest {

    @Test
    @DisplayName("provider=gitee（默认）：恰好一个 RepoProviderClient，且是 Gitee 实现")
    void giteeSelected() {
        try (AnnotationConfigApplicationContext ctx = contextWith("gitee")) {
            Map<String, RepoProviderClient> beans = ctx.getBeansOfType(RepoProviderClient.class);
            assertEquals(1, beans.size(), "必须恰好一个实现，否则接口注入会失败：" + beans.keySet());
            assertTrue(beans.values().iterator().next() instanceof GiteeClient);
        }
    }

    @Test
    @DisplayName("provider 未配置：matchIfMissing 生效，回落到 Gitee（保证既有部署行为不变）")
    void providerMissingDefaultsToGitee() {
        try (AnnotationConfigApplicationContext ctx = contextWith(null)) {
            Map<String, RepoProviderClient> beans = ctx.getBeansOfType(RepoProviderClient.class);
            assertEquals(1, beans.size(), "未配置时也必须有且仅有一个实现：" + beans.keySet());
            assertTrue(beans.values().iterator().next() instanceof GiteeClient);
        }
    }

    @Test
    @DisplayName("provider=gitea：恰好一个 RepoProviderClient，且是 Gitea 实现（Gitee 实现不装配）")
    void giteaSelected() {
        try (AnnotationConfigApplicationContext ctx = contextWith("gitea")) {
            Map<String, RepoProviderClient> beans = ctx.getBeansOfType(RepoProviderClient.class);
            assertEquals(1, beans.size(), "必须恰好一个实现，否则接口注入会失败：" + beans.keySet());
            assertTrue(beans.values().iterator().next() instanceof GiteaProviderClient);
            assertEquals(0, ctx.getBeansOfType(GiteeClient.class).size(),
                    "选了 gitea 就不该再有 GiteeClient Bean");
        }
    }

    /** 构造一个只含两个客户端 + 两个配置类的上下文；provider 为 null 表示不设置该属性。 */
    private AnnotationConfigApplicationContext contextWith(String provider) {
        AnnotationConfigApplicationContext ctx = new AnnotationConfigApplicationContext();
        ctx.register(ObjectMapper.class);   // 无参构造，直接交给容器实例化
        if (provider != null) {
            TestPropertyValues.of("aioa.repo.provider=" + provider).applyTo(ctx);
        }
        ctx.register(GiteeConfig.class, GiteaConfig.class, GiteeClient.class, GiteaProviderClient.class);
        ctx.refresh();
        return ctx;
    }
}
