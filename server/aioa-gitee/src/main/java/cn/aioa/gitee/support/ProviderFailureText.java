package cn.aioa.gitee.support;

import java.util.Locale;

/**
 * 托管方失败 → 面向用户的文案（纯函数：无 Spring 依赖、无副作用、同一输入恒等输出）。
 *
 * <p><b>为什么必须单独抽一层</b>：{@code gitee_repo_member.last_error} 与
 * {@code gitee_project.error_msg} 不是内部字段，它们**直接渲染给租户管理员** ——
 * 成员表的同步失败悬浮说明、项目详情页的红色告警标题都取这两个值。
 * 而托管方返回的 {@code message} 是写给机器看的：Gitea 在「协作者用户名不存在」时回的
 * message 恰好是内部操作名 {@code GetUserByName}，限流时回 {@code Rate Limit Exceeded}。
 * 原文照抄进这两个字段，用户看到的是一串看不懂的英文，而且不知道下一步该做什么
 * （真机实测：成员表里 6 行 {@code GetUserByName}、4 行 {@code Not Found}）。</p>
 *
 * <p><b>约定</b>：按 HTTP 状态给出「中文归因 + 可执行动作」，并把托管方原文附在末尾括号里
 * 保留排障可追溯性 —— 原文不再担任正文，但也不丢。落库处按 250 字截断，截断只会切到
 * 末尾的原文部分，不影响正文动作指引。</p>
 *
 * <p>托管方名一律由调用方以 {@code label} 传入（{@code Gitee} / {@code Gitea}），
 * 本类不写死任何平台名。</p>
 */
public final class ProviderFailureText {

    /** 末尾附带的托管方原文上限（正文通常 60~120 字，整体不超过落库处的 250 字截断）。 */
    static final int RAW_LIMIT = 80;

    /** 托管方名缺失时的中性兜底（不写死平台名，避免切换托管方后谎报）。 */
    private static final String DEFAULT_LABEL = "代码托管平台";

    private ProviderFailureText() {
    }

    /**
     * 成员权限同步失败的用户可见文案。
     *
     * @param status  托管方返回的 HTTP 状态；{@code 0} 表示连接层失败（未拿到响应）
     * @param raw     托管方原始信息，可空
     * @param label   托管方展示名（如 {@code Gitea}）
     * @param owner   仓库归属组织，可空
     * @param repo    仓库名，可空
     * @param username 该成员绑定的托管方登录名，可空
     */
    public static String forMemberSync(int status, String raw, String label,
                                       String owner, String repo, String username) {
        String l = label(label);
        String target = where(owner, repo);
        String who = quoted(username);
        String body = switch (status) {
            case 0 -> l + " 连接失败，稍后将自动重试。";
            case 401 -> l + " 授权已失效（令牌不存在或已被撤销），"
                    + "请到「我的 " + l + " 账号」重新绑定后重试。";
            case 403 -> l + " 拒绝访问：令牌缺少「组织」与「仓库」权限，"
                    + "或该令牌所属账号不是目标组织成员。";
            case 422 -> l + " 拒绝了该账号" + who + "：该账号在 " + l
                    + " 当前实例不存在（或尚未加入目标组织），"
                    + "请到「我的 " + l + " 账号」重新绑定后重试。";
            case 404 -> "在 " + l + " 上找不到目标仓库" + target
                    + (who.isEmpty() ? "" : "，也找不到账号" + who)
                    + "：仓库可能尚未在该实例创建；若仓库正常，则是该成员绑定的 " + l
                    + " 账号在当前实例不存在，请到「我的 " + l + " 账号」重新绑定后重试。";
            case 429 -> l + " 接口限流（触发速率上限），稍后将自动重试。";
            default -> status >= 500
                    ? l + " 服务端异常（HTTP " + status + "），稍后将自动重试。"
                    : l + " 返回 HTTP " + status + "，本次无法同步成员权限。";
        };
        return withRaw(body, raw, l);
    }

    /**
     * 项目 / 仓库生命周期（建仓、配 Webhook、删仓）失败的用户可见文案。
     *
     * @param status 托管方返回的 HTTP 状态；{@code 0} 表示连接层失败（未拿到响应）
     * @param raw    托管方原始信息，可空
     * @param label  托管方展示名（如 {@code Gitea}）
     * @param owner  仓库归属组织，可空
     * @param repo   仓库名，可空
     */
    public static String forProjectLifecycle(int status, String raw, String label,
                                             String owner, String repo) {
        String l = label(label);
        String target = where(owner, repo);
        String body = switch (status) {
            case 0 -> l + " 连接失败，稍后将自动重试。";
            case 401 -> l + " 授权已失效（令牌不存在或已被撤销），"
                    + "请在「企业 " + l + " 初始化」重新填写企业令牌。";
            case 403 -> l + " 拒绝访问：企业令牌缺少「组织」与「仓库」权限，"
                    + "或令牌所属账号不是目标组织成员。";
            case 404 -> "在 " + l + " 上找不到" + target
                    + "：该组织或仓库尚未在当前实例创建。";
            case 422 -> l + " 拒绝了该仓库名（同名仓库已存在或路径被占用）。";
            case 429 -> l + " 接口限流（触发速率上限），稍后将自动重试。";
            default -> status >= 500
                    ? l + " 服务端异常（HTTP " + status + "），稍后将自动重试。"
                    : l + " 返回 HTTP " + status + "，本次操作未完成。";
        };
        return withRaw(body, raw, l);
    }

    /**
     * 「配置 Webhook」这一步失败的用户可见文案（失败原因来自**平台自身**，不是托管方返回）。
     *
     * <p><b>为什么这一步必须有独立文案</b>：项目状态机是
     * {@code CREATING →（建仓 + 配 Webhook 均成功）→ ACTIVE}，而建仓与配 Webhook 是两条任务。
     * 建仓成功、配 Webhook 失败时，任务队列只把**任务**判死，项目自己没有终态迁移 ——
     * 真机实测（2026-09-18）：四条项目在界面上永远显示「创建中」，既没有失败提示，
     * 也没有任何东西会再动它们（定时校准只处理 ACTIVE）。用户唯一的感受是「点了没反应」。</p>
     *
     * <p>本方法把「哪一步失败 + 项目现在是什么状态 + 下一步点什么」讲清楚，
     * 并把原因原文照抄（原因文本本身已是中文且可执行，如「未配置 xxx.webhook-base-url」）。</p>
     *
     * @param raw   失败原因原文，可空
     * @param label 托管方展示名（如 {@code Gitea}）
     */
    public static String forWebhookStep(String raw, String label) {
        String l = label(label);
        String cause = trim(raw);
        if (cause.isEmpty()) {
            cause = "未拿到具体原因，请到任务队列查看该项目的 Webhook 配置任务";
        }
        return "建仓已完成，但「配置 " + l + " Webhook」这一步没成功，项目因此停在未就绪状态："
                + cause + "。按上面的提示处理好之后，点「重试建仓」即可只重跑这一步。";
    }

    /**
     * 「账号绑定（OAuth2 授权码）」失败的用户可见文案。
     *
     * <p><b>为什么不能照抄托管方原文</b>：绑定结果页是**用户直接看见的一页**
     * （{@code GET /gitee/bind/callback} 渲染的 HTML，标题就是「绑定失败」）。
     * 托管方换令牌失败时回的是 {@code error_description}，形如
     * {@code invalid client secret}（平台密钥配置问题）与 {@code client is not authorized}
     * （授权码问题）—— 两者性质完全不同，但都是「用户看不懂、也不知道该找谁」的英文短语。</p>
     *
     * <p><b>与另两处失败文案的判据不同</b>：换令牌失败恒为 HTTP 400，状态码没有区分度，
     * 因此这里按**原因短语特征**分支，而不是按状态码。</p>
     *
     * @param raw   托管方原始原因（通常是 {@code error_description}，可能已带 {@code error} 码），可空
     * @param label 托管方展示名（如 {@code Gitea}）
     */
    public static String forOauthBind(String raw, String label) {
        String l = label(label);
        String r = trim(raw).toLowerCase(Locale.ROOT);
        String body;
        if (r.isEmpty()) {
            body = "未能从 " + l + " 取得授权结果，请返回平台重新发起绑定。";
        } else if (r.contains("data too long") || r.contains("data truncation")) {
            // 令牌写库被列宽截断 —— 这是**平台自身**的存储缺陷，不是用户的授权问题。
            // 2026-09-18 真机实测：Gitea 签发 600~1000 字符的 JWT，而 access_token 列当时是
            // 按 Gitee 的 32~40 字符短串设的 VARCHAR(1024)，密文（AES-GCM + base64）再涨 1/3，
            // 直接超限；回调页只甩一句 "Data too long for column 'access_token'"，用户完全
            // 无从判断该找谁。V55 已把令牌列放宽为 TEXT；本分支保证同类缺陷**再犯时文案上
            // 就指向平台**，而不是继续把一句 SQL 错误丢给用户。
            // 必须排在 "scope"/"permission" 分支**之前**：列名恰好叫 scope 时（"Data too long
            // for column 'scope'"）也含 "scope"，否则会被误判成「用户没勾权限」。
            body = "平台侧存储列宽不足以保存 " + l + " 返回的令牌（属平台缺陷，与你的账号无关）："
                    + "请把下面原文反馈给平台运维，由其扩充列宽后重试。";
        } else if (r.contains("client secret") || r.contains("invalid_client")) {
            body = "平台侧应用密钥与 " + l + " 登记的不一致（属平台配置问题，与你的账号无关）："
                    + "请联系平台运维在 " + l + " 重置该 OAuth 应用的密钥，并同步更新平台配置。";
        } else if (r.contains("redirect")) {
            body = "回调地址与 " + l + " 登记的重定向 URI 不一致："
                    + "请联系平台运维核对两端是否逐字符相同。";
        } else if (r.contains("not authorized") || r.contains("invalid_grant")
                || r.contains("code") || r.contains("expired")) {
            body = "授权码无效或已过期（重复使用、超期未用、或与本次会话不匹配都会如此）："
                    + "请返回平台重新发起绑定。";
        } else if (r.contains("forbidden") || r.contains("scope") || r.contains("permission")) {
            body = "本次授权缺少所需权限范围：请在 " + l + " 重新授权，"
                    + "并确认勾选了仓库与组织相关的权限。";
        } else {
            body = l + " 拒绝了本次授权：请返回平台重新发起绑定。";
        }
        return withRaw(body, raw, l);
    }

    // ==================================================================
    // 内部（同样是纯函数，便于单测直接覆盖）
    // ==================================================================

    /** 正文 + 末尾原文。原文空白则不追加，避免出现「原始返回：」。 */
    private static String withRaw(String body, String raw, String label) {
        String r = trim(raw);
        if (r.isEmpty()) {
            return body;
        }
        return body + "（" + label + " 原始返回：" + shorten(r, RAW_LIMIT) + "）";
    }

    /** 仓库定位串：两者都有则 {@code owner/repo}，只有一个就用那一个，都没有则空。 */
    private static String where(String owner, String repo) {
        String o = trim(owner);
        String r = trim(repo);
        if (o.isEmpty() && r.isEmpty()) {
            return "";
        }
        if (o.isEmpty()) {
            return " " + r;
        }
        if (r.isEmpty()) {
            return " " + o;
        }
        return " " + o + "/" + r;
    }

    private static String quoted(String s) {
        String t = trim(s);
        return t.isEmpty() ? "" : "「" + t + "」";
    }

    private static String label(String label) {
        String l = trim(label);
        return l.isEmpty() ? DEFAULT_LABEL : l;
    }

    private static String trim(String s) {
        return s == null ? "" : s.strip();
    }

    static String shorten(String s, int limit) {
        return s.length() <= limit ? s : s.substring(0, limit) + "…";
    }
}
