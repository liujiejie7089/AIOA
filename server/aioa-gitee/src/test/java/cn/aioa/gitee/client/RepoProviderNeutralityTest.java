package cn.aioa.gitee.client;

import cn.aioa.gitee.config.GiteaProperties;
import cn.aioa.gitee.config.GiteeProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 托管方切换后的两类**静默失效**防回归。
 *
 * <p>这两类缺陷的共同点：编译能过、启动能起、接口返回 200，
 * 只在真机上表现为「页面没内容」「兜底逻辑不生效」。</p>
 */
class RepoProviderNeutralityTest {

    @Test
    @DisplayName("默认分支名必须随托管方：Gitee=master、Gitea=main（写错会让读写文件全部 404）")
    void defaultBranchIsProviderSpecific() {
        RepoProviderClient gitee = new GiteeClient(new GiteeProperties(), new ObjectMapper());
        RepoProviderClient gitea = new GiteaProviderClient(new GiteaProperties(), new ObjectMapper());
        assertEquals("master", gitee.defaultBranch());
        assertEquals("main", gitea.defaultBranch(), "Gitea 1.26 实例实测默认分支为 main");
    }

    /**
     * 源码审计：服务层不得按 Gitee 专有异常类型捕获。
     *
     * <p>为什么用源码审计而不是运行期断言：这是**类型选择**错误，只要有人新写一处
     * {@code catch (GiteeApiException)}，在 Gitea 下该分支就永久不可达，而任何
     * 「跑一遍 happy path」的测试都不会发现它。</p>
     */
    @Test
    @DisplayName("服务层不得 catch GiteeApiException（Gitea 抛中立基类，按专有类型捕获会漏接）")
    void servicesMustCatchNeutralException() throws IOException {
        Path serviceDir = Path.of("src", "main", "java", "cn", "aioa", "gitee", "service");
        Assumptions.assumeTrue(Files.isDirectory(serviceDir),
                "非模块根目录运行，跳过源码审计：" + serviceDir.toAbsolutePath());

        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(serviceDir)) {
            for (Path f : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                String src = Files.readString(f, StandardCharsets.UTF_8);
                if (src.contains("catch (GiteeApiException") || src.contains("new GiteeApiException(")) {
                    offenders.add(serviceDir.relativize(f).toString());
                }
            }
        }
        assertTrue(offenders.isEmpty(),
                "以下文件按 Gitee 专有异常类型处理，Gitea 下该分支不可达：" + offenders);
    }

    /**
     * 源码审计：{@code gitee_account} 的**每一次条件查询**都必须带 provider 过滤。
     *
     * <p>为什么必须这样守：绑定行是**按托管方归属**的身份数据（uid / 登录名 / 用该平台
     * 密钥加密的令牌）。漏掉过滤不会报错，只会让 Gitea 侧拿到 Gitee 的身份 ——
     * 真机表现是「建项目 500（解密 Tag mismatch）」「成员同步 404（拿 Gitee 登录名去
     * Gitea 加协作者）」。这类缺陷任何 happy-path 用例都测不出来，只有源码审计能守住。</p>
     *
     * <p>只审「带 {@code LambdaQueryWrapper<GiteeAccount>} 的查询」：{@code selectById} /
     * {@code insert} / {@code updateById} 按主键操作，天然无歧义，不在审计范围。</p>
     */
    @Test
    @DisplayName("gitee_account 的条件查询必须按 provider 过滤（漏了会把异平台身份当自己的用）")
    void accountQueriesMustBeProviderScoped() throws IOException {
        Path root = Path.of("src", "main", "java", "cn", "aioa", "gitee");
        Assumptions.assumeTrue(Files.isDirectory(root), "非模块根目录运行，跳过源码审计：" + root);

        String marker = "LambdaQueryWrapper<GiteeAccount>()";
        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(root)) {
            for (Path f : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                String src = Files.readString(f, StandardCharsets.UTF_8);
                int idx = 0;
                while ((idx = src.indexOf(marker, idx)) >= 0) {
                    int end = src.indexOf(';', idx);
                    if (end < 0) {
                        end = src.length();
                    }
                    String block = src.substring(idx, end);
                    if (!block.contains("GiteeAccount::getProvider")) {
                        offenders.add(root.relativize(f) + " @" + idx
                                + " → " + block.replaceAll("\\s+", " ").substring(0, Math.min(160, block.length())));
                    }
                    idx = end;
                }
            }
        }
        assertTrue(offenders.isEmpty(),
                "以下 gitee_account 查询未按 provider 过滤（切托管方后会读到异平台身份）：" + offenders);
    }

    /**
     * 源码审计：service / controller / support 下**面向用户的文案**不得写死托管方名。
     *
     * <p>判据：出现 {@code Gitee }（Gitee + 一个空格）即命中 —— 句首、句中、句尾都算
     * （真机实测踩过：「仅移除平台项目，Gitee 仓库保留」这种句中写法，只查句首会漏）。
     * {@code GiteeRepoTaskHandler} 之类的类名因为「Gitee」后面不是空格，不会被误伤；
     * 托管方专有的实现包（{@code client/} 与 {@code config/}）本就该说 Gitee ——
     * 适配器正是那个「把名字集中到一处」的地方，所以不在审计范围。</p>
     *
     * <p>两类豁免：注释（不呈现给用户）与 {@code log.*}（只在运维视野里，带上平台名有助排障）。</p>
     */
    @Test
    @DisplayName("面向用户的文案不得写死托管方名（只有注释与日志可以）")
    void userFacingCopyMustNotHardcodeProviderName() throws IOException {
        Path root = Path.of("src", "main", "java", "cn", "aioa", "gitee");
        Assumptions.assumeTrue(Files.isDirectory(root), "非模块根目录运行，跳过源码审计：" + root);
        List<String> audited = List.of("service", "controller", "support");

        String needle = "Gitee ";
        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(root)) {
            for (Path f : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                Path rel = root.relativize(f);
                if (audited.stream().noneMatch(rel::startsWith)) {
                    continue;
                }
                List<String> lines = Files.readAllLines(f, StandardCharsets.UTF_8);
                for (int i = 0; i < lines.size(); i++) {
                    String t = lines.get(i).strip();
                    if (t.startsWith("//") || t.startsWith("*") || t.startsWith("/*") || t.contains("log.")) {
                        continue;
                    }
                    int inline = t.indexOf("//");          // 去掉行尾注释再判
                    if (inline >= 0) {
                        t = t.substring(0, inline);
                    }
                    if (t.contains(needle)) {
                        offenders.add(rel + ":" + (i + 1) + " → " + t);
                    }
                }
            }
        }
        assertTrue(offenders.isEmpty(),
                "以下面向用户的文案写死了托管方名（gitea 接线下会谎报平台）：" + offenders);
    }
}
