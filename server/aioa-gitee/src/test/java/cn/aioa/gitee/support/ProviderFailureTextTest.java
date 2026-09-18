package cn.aioa.gitee.support;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 用户可见失败文案的映射规则（{@link ProviderFailureText}）。
 *
 * <p>这些断言守的是「失败原因能不能被用户看懂并据此行动」，不是措辞好看与否：
 * 每个用例都固定住「必须出现的中文归因 / 动作」与「必须保留的托管方原文」，
 * 任何一侧被改掉都会在这里红掉。</p>
 */
class ProviderFailureTextTest {

    private static final String GITEA = "Gitea";
    private static final String GITEE = "Gitee";

    // ==================================================================
    // 真机原始值 → 用户可读（本类存在的理由）
    // ==================================================================

    @Test
    @DisplayName("真机原值 GetUserByName（Gitea 的内部操作名）不得作为正文出现，但必须被保留")
    void opaqueGiteaMessageIsNotTheBody() {
        // 真机实测：PUT /repos/{o}/{r}/collaborators/dsj_admin -> 404
        //   message="GetUserByName"  errors=["user does not exist [name: dsj_admin]"]
        // 客户端已把两者拼成 detail（message）后传进来
        String raw = "user does not exist [name: dsj_admin]（GetUserByName）";
        String got = ProviderFailureText.forMemberSync(
                404, raw, GITEA, "AI-OA", "dept101-x", "dsj_admin");

        assertFalse(got.startsWith("GetUserByName"),
                "裸内部操作名不能当正文（用户看不懂也不知道做什么）：" + got);
        assertTrue(got.contains("重新绑定"), "404 必须给出可执行动作：重新绑定：" + got);
        assertTrue(got.contains("我的 " + GITEA + " 账号"), "动作要指向具体入口：" + got);
        assertTrue(got.contains("AI-OA/dept101-x"), "要点明是哪个仓库：" + got);
        assertTrue(got.contains("「dsj_admin」"), "要点明是哪个账号：" + got);
        assertTrue(got.contains("原始返回：user does not exist"), "原文必须保留以备排障：" + got);
        assertTrue(hasChinese(got), "正文必须是中文：" + got);
    }

    @Test
    @DisplayName("真机原值 Rate Limit Exceeded 必须被归因为「限流 + 会自动重试」")
    void rateLimitIsExplainedAsRetryable() {
        String got = ProviderFailureText.forProjectLifecycle(
                429, "Rate Limit Exceeded", GITEA, "AI-OA", "dept101-x");

        assertFalse(got.startsWith("Rate Limit Exceeded"), "英文原文不能当正文：" + got);
        assertTrue(got.contains("限流"), got);
        assertTrue(got.contains("自动重试"), "必须告诉用户「不用管，会重试」：" + got);
        assertTrue(got.contains("原始返回：Rate Limit Exceeded"), got);
    }

    @Test
    @DisplayName("真机原值 401 Unauthorized: Access token does not exist 必须指向「重新填企业令牌」")
    void expiredTokenPointsToTheRightPlace() {
        String got = ProviderFailureText.forProjectLifecycle(
                401, "401 Unauthorized: Access token does not exist", GITEA, "AI-OA", "r");

        assertTrue(got.contains("授权已失效"), got);
        assertTrue(got.contains("企业 " + GITEA + " 初始化"), "动作要指向企业初始化入口：" + got);
    }

    // ==================================================================
    // 状态 → 归因（成员同步）
    // ==================================================================

    @Test
    @DisplayName("成员同步：连接层失败（status=0）归因为连接失败且可重试")
    void memberConnectFailure() {
        String got = ProviderFailureText.forMemberSync(0, "连接 Gitea 失败：ConnectException", GITEA, null, null, null);
        assertTrue(got.contains("连接失败") && got.contains("自动重试"), got);
    }

    @Test
    @DisplayName("成员同步：401 指向「我的 xx 账号」重新绑定")
    void member401() {
        String got = ProviderFailureText.forMemberSync(401, "Unauthorized", GITEA, "o", "r", "u");
        assertTrue(got.contains("授权已失效") && got.contains("我的 " + GITEA + " 账号"), got);
    }

    @Test
    @DisplayName("成员同步：403 归因为「组织/仓库权限」而不是「重新授权」")
    void member403() {
        String got = ProviderFailureText.forMemberSync(403, "forbidden", GITEA, "o", "r", "u");
        assertTrue(got.contains("拒绝访问") && got.contains("组织") && got.contains("仓库"), got);
        assertFalse(got.contains("重新绑定"), "403 不是授权失效，不该让用户去重新绑定：" + got);
    }

    @Test
    @DisplayName("成员同步：404 同时点出「仓库」与「账号」两种可能（Gitea 的 404 两者都可能是）")
    void member404MentionsBothCandidates() {
        String got = ProviderFailureText.forMemberSync(404, "Not Found", GITEA, "o", "r", "u");
        assertTrue(got.contains("找不到目标仓库"), got);
        assertTrue(got.contains("找不到账号"), got);
    }

    @Test
    @DisplayName("成员同步：无登录名时 404 只提仓库，不出现空的「找不到账号」")
    void member404WithoutUsername() {
        String got = ProviderFailureText.forMemberSync(404, "Not Found", GITEA, "o", "r", null);
        assertTrue(got.contains("找不到目标仓库"), got);
        assertFalse(got.contains("找不到账号"), got);
    }

    @Test
    @DisplayName("成员同步：5xx 归因为服务端异常且可重试")
    void member5xx() {
        for (int s : new int[]{500, 502, 503}) {
            String got = ProviderFailureText.forMemberSync(s, "internal", GITEA, "o", "r", "u");
            assertTrue(got.contains("服务端异常") && got.contains("HTTP " + s), got);
        }
    }

    @Test
    @DisplayName("成员同步：422「用户不存在」必须归因为账号在当前实例不存在（Gitea 实测返回码）")
    void member422UnknownAccount() {
        // 真机实测：PUT /repos/{o}/{r}/collaborators/{name} → 422
        //   {"message":"user does not exist [uid: 0, name: no-such-gitea-user-xyz]"}
        String got = ProviderFailureText.forMemberSync(422,
                "user does not exist [uid: 0, name: no-such-gitea-user-xyz]", GITEA, "o", "r", "u");

        assertTrue(got.contains("当前实例不存在"), got);
        assertTrue(got.contains("我的 " + GITEA + " 账号") && got.contains("重新绑定"), got);
        assertTrue(got.contains("user does not exist"), "原文必须保留：" + got);
        assertFalse(got.contains("同名仓库"), "这是成员同步，不该套用建仓的 422 文案：" + got);
    }

    @Test
    @DisplayName("成员同步：未单独归因的状态也要带状态码，而不是只剩英文原文")
    void memberOtherStatus() {
        String got = ProviderFailureText.forMemberSync(409, "Conflict", GITEA, "o", "r", "u");
        assertTrue(got.contains("HTTP 409"), got);
        assertTrue(hasChinese(got), got);
    }

    // ==================================================================
    // 状态 → 归因（项目生命周期）
    // ==================================================================

    @Test
    @DisplayName("项目：404 归因为「组织或仓库未在该实例创建」")
    void project404() {
        String got = ProviderFailureText.forProjectLifecycle(404, "Not Found", GITEA, "AI-OA", "r");
        assertTrue(got.contains("AI-OA/r") && got.contains("未在当前实例创建"), got);
    }

    @Test
    @DisplayName("项目：422 归因为「仓库名被占用」（建仓前已识别「已存在」时不会走到这里）")
    void project422() {
        String got = ProviderFailureText.forProjectLifecycle(422, "repo name has been used", GITEA, "o", "r");
        assertTrue(got.contains("拒绝") && got.contains("同名"), got);
    }

    @Test
    @DisplayName("项目：401 指向「企业 xx 初始化」重新填令牌")
    void project401() {
        String got = ProviderFailureText.forProjectLifecycle(401, "Unauthorized", GITEA, "o", "r");
        assertTrue(got.contains("企业 " + GITEA + " 初始化"), got);
    }

    // ==================================================================
    // 托管方名与原文处理
    // ==================================================================

    @Test
    @DisplayName("托管方名全程由 label 决定：Gitee 接线逐字说 Gitee，不出现另一个平台名")
    void labelDrivesEveryOccurrence() {
        String gitee = ProviderFailureText.forMemberSync(403, "x", GITEE, "o", "r", "u");
        assertTrue(gitee.contains(GITEE), gitee);
        assertFalse(gitee.contains(GITEA) && !gitee.contains(GITEE),
                "不应出现 Gitea：" + gitee);

        String gitea = ProviderFailureText.forMemberSync(403, "x", GITEA, "o", "r", "u");
        assertTrue(gitea.contains(GITEA), gitea);
        assertFalse(gitea.contains(GITEE), "Gitea 接线不得出现 Gitee：" + gitea);
    }

    @Test
    @DisplayName("label 为空时用中性词兜底，不得留空或写出某个平台名")
    void blankLabelFallsBackNeutrally() {
        for (String blank : new String[]{null, "", "   "}) {
            String got = ProviderFailureText.forMemberSync(401, null, blank, "o", "r", "u");
            assertTrue(got.contains("代码托管平台"), got);
            assertFalse(got.contains(GITEE) || got.contains(GITEA), got);
        }
    }

    @Test
    @DisplayName("原文为空/空白时不留「原始返回：」空壳")
    void blankRawProducesNoTrailer() {
        for (String blank : new String[]{null, "", "   "}) {
            String got = ProviderFailureText.forProjectLifecycle(429, blank, GITEA, "o", "r");
            assertFalse(got.contains("原始返回"), got);
            assertFalse(got.endsWith("（）"), got);
        }
    }

    @Test
    @DisplayName("超长原文按上限截断并加省略号（正文动作在前，截断只切末尾）")
    void longRawIsShortenedInTrailer() {
        String raw = "x".repeat(500);
        String got = ProviderFailureText.forProjectLifecycle(500, raw, GITEA, "o", "r");
        assertTrue(got.contains("…"), "超长原文应截断：" + got.length());
        assertTrue(got.startsWith("Gitea 服务端异常"), "截断不得影响正文：" + got.substring(0, 40));
    }

    @Test
    @DisplayName("纯函数：同一输入两次调用必须逐字相同（可安全用于断言与重放）")
    void deterministic() {
        String a = ProviderFailureText.forMemberSync(404, "Not Found", GITEA, "o", "r", "u");
        String b = ProviderFailureText.forMemberSync(404, "Not Found", GITEA, "o", "r", "u");
        assertEquals(a, b);
    }

    @Test
    @DisplayName("owner/repo 缺失时不留多余分隔符")
    void whereHandlesMissingParts() {
        assertTrue(ProviderFailureText.forProjectLifecycle(404, null, GITEA, null, null)
                .contains("找不到："), "都没有时不拼分隔符");
        assertTrue(ProviderFailureText.forProjectLifecycle(404, null, GITEA, "o", null)
                .contains(" o："));
        assertTrue(ProviderFailureText.forProjectLifecycle(404, null, GITEA, null, "r")
                .contains(" r："));
    }

    // ==================================================================
    // 账号绑定（OAuth2）失败文案：绑定结果页是用户直接看见的一页
    // ==================================================================

    @Test
    @DisplayName("绑定失败·密钥失配：必须点明是「平台配置问题」并给出找谁办")
    void oauthBindSecretMismatch() {
        String s = ProviderFailureText.forOauthBind(
                "invalid client secret（unauthorized_client）", GITEA);
        assertTrue(hasChinese(s), s);
        assertTrue(s.contains("密钥"), s);
        assertTrue(s.contains("平台运维"), s);
        assertTrue(s.contains("invalid client secret"), "原文必须保留以供排障：" + s);
    }

    @Test
    @DisplayName("绑定失败·授权码问题与密钥问题必须给出不同指引（否则用户不知道找谁）")
    void oauthBindCodeAndSecretAreNotCollapsed() {
        String secret = ProviderFailureText.forOauthBind("invalid client secret", GITEA);
        String code = ProviderFailureText.forOauthBind("client is not authorized", GITEA);
        assertFalse(secret.equals(code), "两种故障给同一句指引等于没给信息");
        assertTrue(code.contains("授权码"), code);
        assertFalse(code.contains("平台运维"), "授权码问题不该让用户去找运维：" + code);
    }

    @Test
    @DisplayName("绑定失败·回调地址不一致：要指向「逐字符核对」")
    void oauthBindRedirectMismatch() {
        String s = ProviderFailureText.forOauthBind("redirect_uri mismatch", GITEA);
        assertTrue(s.contains("重定向 URI"), s);
        assertTrue(s.contains("逐字符"), s);
    }

    @Test
    @DisplayName("绑定失败·无原因：不编造原因，给重试指引且不出现空的「原始返回：」")
    void oauthBindBlankReason() {
        String s = ProviderFailureText.forOauthBind(null, GITEA);
        assertTrue(hasChinese(s), s);
        assertTrue(s.contains("重新发起绑定"), s);
        assertFalse(s.contains("原始返回"), s);
    }

    @Test
    @DisplayName("绑定失败·托管方名随入参注入，缺失时用中性兜底（不谎报平台）")
    void oauthBindLabelIsInjected() {
        assertTrue(ProviderFailureText.forOauthBind("invalid client secret", GITEE).contains("Gitee"));
        assertTrue(ProviderFailureText.forOauthBind("invalid client secret", null)
                .contains("代码托管平台"));
    }

    @Test
    @DisplayName("绑定失败·纯函数：同一输入恒等输出")
    void oauthBindDeterministic() {
        assertEquals(ProviderFailureText.forOauthBind("client is not authorized", GITEA),
                ProviderFailureText.forOauthBind("client is not authorized", GITEA));
    }

    @Test
    @DisplayName("绑定失败·令牌写库被列宽截断：必须点明「平台缺陷、与账号无关」，不甩 SQL 给用户")
    void oauthBindTokenTruncationPointsAtPlatform() {
        // 2026-09-18 真机实测原文（Gitea JWT 放进按 Gitee 短串设的 VARCHAR(1024) 列）
        String s = ProviderFailureText.forOauthBind(
                "Data too long for column 'access_token' at row 1", GITEA);
        assertTrue(hasChinese(s), s);
        assertTrue(s.contains("平台") && s.contains("列宽"), s);
        assertTrue(s.contains("与你的账号无关"), "必须明确排除用户自身原因：" + s);
        assertTrue(s.contains("平台运维"), s);
        assertTrue(s.contains("Data too long for column 'access_token'"),
                "原文必须保留以供排障：" + s);
        assertFalse(s.contains("重新授权"),
                "这是平台侧写库失败，让用户重试授权解决不了问题：" + s);
    }

    @Test
    @DisplayName("绑定失败·列名恰好叫 scope 时，截断不能被误判成「用户没勾权限」")
    void oauthBindTruncationOnScopeColumnIsNotMisfiled() {
        // "scope" 同时出现在截断原文与「权限不足」分支的判据里，分支顺序错了就会归错因
        String s = ProviderFailureText.forOauthBind(
                "Data too long for column 'scope' at row 1", GITEA);
        assertTrue(s.contains("列宽"), s);
        assertFalse(s.contains("勾选"), "不该指引用户去重新勾权限：" + s);
    }

    // ==================================================================
    // 「配置 Webhook」这一步失败（项目停在 CREATING 的那个缺口）
    // ==================================================================

    @Test
    @DisplayName("配 Webhook 失败：必须说清「建仓成功、卡在这一步、下一步点什么」")
    void webhookStepSaysWhichStepAndWhatToDo() {
        // 2026-09-18 真机实测原文：建仓成功，配 Webhook 抛 IllegalStateException，
        // 任务被判死而项目永远停在 CREATING，界面上只有「创建中」三个字。
        String s = ProviderFailureText.forWebhookStep(
                "未配置 aioa.gitea.webhook-base-url，Gitea 无法回调本机地址；"
                        + "请填写平台对 Gitea 可见的公网地址", GITEA);

        assertTrue(hasChinese(s), s);
        assertTrue(s.contains("建仓已完成"), "要让用户知道仓库其实已经建好了：" + s);
        assertTrue(s.contains("配置 " + GITEA + " Webhook"), "要点明失败的是哪一步：" + s);
        assertTrue(s.contains("未就绪"), "要点明项目当前的真实状态（而不是「创建中」）：" + s);
        assertTrue(s.contains("webhook-base-url"), "原因原文必须保留，否则用户无从下手：" + s);
        assertTrue(s.contains("重试建仓"), "必须给出可执行动作，且与界面按钮同名：" + s);
    }

    @Test
    @DisplayName("配 Webhook 失败·原因为空时：不出现空白正文，指向任务队列")
    void webhookStepWithoutCauseStillActionable() {
        String s = ProviderFailureText.forWebhookStep(null, GITEA);
        assertTrue(hasChinese(s), s);
        assertTrue(s.contains("任务队列"), s);
        assertFalse(s.contains("：。"), "原因为空时不得拼出「：。」这种残缺句：" + s);
    }

    @Test
    @DisplayName("配 Webhook 失败·托管方名按入参走，不写死 Gitee")
    void webhookStepUsesGivenLabel() {
        assertTrue(ProviderFailureText.forWebhookStep("x", GITEA).contains(GITEA + " Webhook"));
        assertTrue(ProviderFailureText.forWebhookStep("x", GITEE).contains(GITEE + " Webhook"));
        assertFalse(ProviderFailureText.forWebhookStep("x", GITEA).contains(GITEE));
    }

    private static boolean hasChinese(String s) {
        return s != null && s.codePoints().anyMatch(c -> c >= 0x4E00 && c <= 0x9FFF);
    }
}
