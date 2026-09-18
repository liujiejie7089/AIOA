package cn.aioa.gitee.service;

import cn.aioa.gitee.client.RepoProviderException;
import cn.aioa.gitee.client.RepoProviderClient;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.entity.GiteeTask;
import cn.aioa.gitee.mapper.GiteeProjectMapper;
import cn.aioa.gitee.support.ProviderFailureText;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

/**
 * 仓库生命周期任务处理器：建仓 / 配 Webhook / 删仓。
 *
 * <p><b>幂等设计</b>（Gitee 调用可能成功但本地写库失败，从而被重试）：</p>
 * <ul>
 *   <li>建仓遇「已存在」→ 不报错，改为 {@code GET /repos} **认领**已存在的仓库
 *       （否则一次网络抖动就让项目永久卡在失败态，而远端仓库其实已经建好了）；</li>
 *   <li>配 Webhook 前先列出现有 hooks，若回调地址已存在则直接复用其 id，
 *       避免重试时在仓库上挂出多个重复 Webhook（每个都会重复投递事件）。</li>
 * </ul>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class GiteeRepoTaskHandler implements GiteeTaskHandler {

    private static final SecureRandom RANDOM = new SecureRandom();

    /**
     * 平台对仓库事件的订阅开关（push / 合并请求 / 议题 / 评论）。
     *
     * <p>建钩子用这四个开关，落库的「事件」列表也必须由**同一组开关**推出 ——
     * 否则会出现「详情页说订的是 A，仓库上实际订的是 B」。
     * 历史上这里落库写死了 Gitee 词表（{@code push,merge_requests,issues,notes}），
     * 切到 Gitea 后详情页就把 {@code merge_requests} / {@code notes} 显示给用户，
     * 而仓库上真实订的是 {@code pull_request} / {@code issue_comment}。</p>
     */
    private static final boolean HOOK_PUSH = true;
    private static final boolean HOOK_PR = true;
    private static final boolean HOOK_ISSUE = true;
    private static final boolean HOOK_NOTE = true;

    private final GiteeProjectMapper projectMapper;
    private final RepoProviderClient client;
    private final RepoProviderSettings props;
    private final GiteeTokenService tokenService;
    private final GiteeTaskService taskService;
    private final GiteeMemberService memberService;
    private final GiteeTenantConfigService tenantConfigService;

    @Override
    public List<String> types() {
        return List.of(GiteeTask.TYPE_CREATE_REPO, GiteeTask.TYPE_CONFIGURE_WEBHOOK,
                GiteeTask.TYPE_DELETE_REPO, GiteeTask.TYPE_DELETE_WEBHOOK);
    }

    @Override
    public void handle(GiteeTask task) throws Exception {
        switch (task.getTaskType()) {
            case GiteeTask.TYPE_CREATE_REPO -> createRepo(task);
            case GiteeTask.TYPE_CONFIGURE_WEBHOOK -> configureWebhook(task);
            case GiteeTask.TYPE_DELETE_REPO -> deleteRepo(task);
            case GiteeTask.TYPE_DELETE_WEBHOOK -> deleteWebhook(task);
            default -> throw new IllegalStateException("GiteeRepoTaskHandler 不支持：" + task.getTaskType());
        }
    }

    // ======================================================================
    // 建仓
    // ======================================================================

    private void createRepo(GiteeTask task) {
        GiteeProject p = projectMapper.selectById(task.getBizId());
        if (p == null) {
            return;
        }
        String token = tokenService.requireAccessTokenForProject(p);
        String owner = targetOwner(p);
        try {
            Map<String, Object> repo;
            try {
                repo = StringUtils.hasText(owner)
                        ? client.createOrgRepo(token, owner, p.getName(), p.getRepoName(),
                        p.getDescription(), !"public".equals(p.getVisibility()), true)
                        : client.createUserRepo(token, p.getRepoName(), p.getDescription(),
                        !"public".equals(p.getVisibility()), true);
            } catch (RepoProviderException e) {
                if (isAlreadyExists(e)) {
                    // 远端已存在（多为「上次调用成功但写库失败」后的重试）→ 认领而不是报错
                    log.info("Gitee 仓库已存在，改为认领：{}/{}", owner, p.getRepoName());
                    repo = client.getRepo(token, owner, p.getRepoName());
                } else {
                    // 用户可见文案：按状态归因 + 给动作，原文附末尾（详见 ProviderFailureText）
                    markFailed(p, ProviderFailureText.forProjectLifecycle(e.getStatus(), e.getMessage(),
                            props.providerLabel(), owner, p.getRepoName()));
                    throw e;
                }
            }
            GiteeProject upd = new GiteeProject();
            upd.setId(p.getId());
            upd.setGiteeOwner(owner);
            upd.setGiteeRepo(str(repo.get("path"), p.getRepoName()));
            upd.setGiteeRepoId(asLong(repo.get("id")));
            upd.setGiteeHtmlUrl(webUrl(repo));
            upd.setGiteeSshUrl(str(repo.get("ssh_url"), null));
            upd.setGiteeHttpsUrl(cloneUrl(repo));
            // 优先取接口返回的 default_branch（实例可自行配置）；接口没给才回落平台默认值
            // —— 回落值也不能写死 master，否则 Gitea（main）上读写文件会全部 404。
            upd.setDefaultBranch(str(repo.get("default_branch"), client.defaultBranch()));
            upd.setErrorMsg(null);
            upd.setUpdatedAt(LocalDateTime.now());
            projectMapper.updateById(upd);

            // 建仓成功 → 立刻排「配 Webhook」，而不是在同一任务里连着做：
            // 两步各自可重试，失败定位也更清楚（是建仓失败还是配 Webhook 失败）
            taskService.enqueue(p.getTenantId(), GiteeTask.TYPE_CONFIGURE_WEBHOOK,
                    "PROJECT", p.getId(), Map.of());
        } catch (RepoProviderException e) {
            throw e;
        } catch (Exception e) {
            markFailed(p, e.getMessage());
            throw e;
        }
    }

    // ======================================================================
    // 配置 Webhook
    // ======================================================================

    private void configureWebhook(GiteeTask task) {
        GiteeProject p = projectMapper.selectById(task.getBizId());
        if (p == null || !StringUtils.hasText(p.getGiteeRepo())) {
            return;
        }
        try {
            doConfigureWebhook(p);
        } catch (RepoProviderException e) {
            // 与 createRepo 对称：托管方拒绝时把项目一并判死并写清原因
            markFailed(p, ProviderFailureText.forProjectLifecycle(e.getStatus(), e.getMessage(),
                    props.providerLabel(), p.getGiteeOwner(), p.getGiteeRepo()));
            throw e;
        } catch (Exception e) {
            // 非托管方异常（回调基址未配、企业令牌解不开、密钥被换过…）都是**永久**失败：
            // 任务不会重试，若此处不把项目判死，项目将永远停在 CREATING 且界面毫无提示。
            // 真机实测（2026-09-18）：4 条项目就这样挂在「创建中」不动。
            markFailed(p, ProviderFailureText.forWebhookStep(e.getMessage(), props.providerLabel()));
            throw e;
        }
    }

    private void doConfigureWebhook(GiteeProject p) {
        String token = tokenService.requireAccessTokenForProject(p);
        String callback = callbackUrl(p.getId());

        List<Map<String, Object>> existing = client.listHooks(token, p.getGiteeOwner(), p.getGiteeRepo());

        // 自愈：清掉本仓库上**指向别的项目**的平台钩子。
        // 场景：项目 A 建仓后没删仓就删了项目（钩子清理任务失败），之后项目 B 用同一路径
        // 重建并认领了这个仓库 —— 此时仓库上同时挂着 A 与 B 的钩子，事件会被投递两遍。
        for (Map<String, Object> hook : existing) {
            String url = str(hook.get("url"), null);
            Long id = asLong(hook.get("id"));
            if (url != null && isPlatformHook(url) && !url.equals(callback)) {
                try {
                    client.deleteHook(token, p.getGiteeOwner(), p.getGiteeRepo(), id);
                    log.info("清理历史遗留 Webhook project={} hookId={} url={}", p.getId(), id, url);
                } catch (RepoProviderException e) {
                    // 清不掉不影响本次配置，记日志即可（可能是权限或已被删）
                    log.warn("清理遗留 Webhook 失败 hookId={}：{}", id, e.getMessage());
                }
            }
        }

        // 幂等：已配过同一个回调地址就复用，避免重试挂出多个重复 Webhook
        for (Map<String, Object> hook : existing) {
            if (callback.equals(str(hook.get("url"), null))) {
                Long id = asLong(hook.get("id"));
                saveWebhook(p, id, callback);
                return;
            }
        }

        // 每仓库独立密钥：单个仓库泄露不影响其他项目（未配置全局密钥时）
        String secret = StringUtils.hasText(props.getWebhookSecret())
                ? props.getWebhookSecret()
                : randomSecret();

        Map<String, Object> hook = client.createHook(token, p.getGiteeOwner(), p.getGiteeRepo(),
                callback, secret, HOOK_PUSH, HOOK_PR, HOOK_ISSUE, HOOK_NOTE);
        Long id = asLong(hook.get("id"));
        saveWebhook(p, id, callback, secret);
    }

    /** 是否是本平台挂的钩子（按回调地址前缀识别，避免误删用户自建的钩子）。 */
    private boolean isPlatformHook(String url) {
        String base = props.getWebhookBaseUrl();
        if (!StringUtils.hasText(base)) {
            return false;
        }
        String prefix = (base.endsWith("/") ? base.substring(0, base.length() - 1) : base)
                + "/api/v1/gitee/webhook/";
        return url.startsWith(prefix);
    }

    // ======================================================================
    // 摘 Webhook（删项目但保留仓库）
    // ======================================================================

    /**
     * 删除平台为该仓库配置的 Webhook。
     *
     * <p>参数全部取自任务 payload 而不是回查项目：本任务正是在项目**已被软删之后**
     * 才执行的，此时 {@code projectMapper.selectById} 已经查不到（逻辑删除过滤），
     * 回查会让这个任务永远「找不到项目」而静默跳过。</p>
     */
    private void deleteWebhook(GiteeTask task) {
        Map<String, Object> payload = taskService.payloadOf(task);
        String owner = str(payload.get("owner"), null);
        String repo = str(payload.get("repo"), null);
        if (!StringUtils.hasText(owner) || !StringUtils.hasText(repo)) {
            log.info("摘 Webhook：缺少仓库信息，跳过 task={}", task.getId());
            return;
        }
        Long hookId = asLong(payload.get("hookId"));
        // 令牌取自项目创建者；项目已软删，只能按 tenant + createdBy 取 —— 这里用 payload
        // 里的 createdBy（入队时写入），拿不到就放弃（钩子会由下次 configureWebhook 自愈清理）
        Long createdBy = asLong(payload.get("createdBy"));
        if (createdBy == null) {
            log.info("摘 Webhook：缺少操作人，跳过 task={}（可由下次建仓自愈清理）", task.getId());
            return;
        }
        String token = tokenService.requireAccessToken(task.getTenantId(), createdBy);
        try {
            if (hookId != null) {
                client.deleteHook(token, owner, repo, hookId);
            } else {
                for (Map<String, Object> hook : client.listHooks(token, owner, repo)) {
                    String url = str(hook.get("url"), null);
                    if (url != null && isPlatformHook(url)) {
                        client.deleteHook(token, owner, repo, asLong(hook.get("id")));
                    }
                }
            }
            log.info("已摘除平台 Webhook {}/{} hookId={}", owner, repo, hookId);
        } catch (RepoProviderException e) {
            // 仓库已不存在（404）= 目标已达成；其余按可重试语义抛给队列
            if (e.getStatus() == 404) {
                log.info("仓库 {}/{} 已不存在，无需摘 Webhook", owner, repo);
                return;
            }
            throw e;
        }
    }

    private void saveWebhook(GiteeProject p, Long hookId, String callback) {
        saveWebhook(p, hookId, callback, null);
    }

    private void saveWebhook(GiteeProject p, Long hookId, String callback, String secret) {
        GiteeProject upd = new GiteeProject();
        upd.setId(p.getId());
        upd.setWebhookId(hookId);
        // 事件名按**当前托管方**的词表落库（展示用）：Gitee 是 merge_requests/notes，
        // Gitea 是 pull_request/issue_comment —— 写死任一方都会让另一方的详情页说谎。
        upd.setWebhookEvents(String.join(",",
                client.hookEventNames(HOOK_PUSH, HOOK_PR, HOOK_ISSUE, HOOK_NOTE)));
        if (secret != null) {
            upd.setWebhookSecret(secret);
        }
        upd.setStatus(GiteeProject.STATUS_ACTIVE);
        upd.setErrorMsg(null);
        upd.setUpdatedAt(LocalDateTime.now());
        projectMapper.updateById(upd);
        log.info("{} Webhook 已配置 project={} hookId={} url={}", props.providerLabel(), p.getId(), hookId, callback);

        // 仓库此时才真正可用 → 到这一步再把创建者登记为仓库管理员成员。
        // 放在建仓之前会让成员同步打在还不存在的仓库上（404 判死）。
        try {
            memberService.ensureCreatorMember(p);
        } catch (Exception e) {
            // 成员补齐失败不应让「项目已就绪」这个主结论回退：仓库与 Webhook 都已成功，
            // 创建者的协作者权限由定时校准补齐（会重试），因此只记日志。
            log.warn("登记项目创建者仓库成员失败 project={}：{}", p.getId(), e.getMessage());
        }
    }

    // ======================================================================
    // 删仓
    // ======================================================================

    private void deleteRepo(GiteeTask task) {
        // 仓库信息一律取自**入队时写入的 payload**，**不能**回读项目行：
        // 项目此刻已被逻辑删除（@TableLogic 置 deleted_at），selectById 会返回 null。
        // 旧实现正是 `selectById` 拿到 null 后静默 return，任务记为 DONE、仓库却从未被删，
        // 而界面上已经告诉用户「已标记删除 Gitee 仓库（不可恢复）」—— 一次静默的假成功。
        // deleteWebhook 一直按 payload 取值，deleteRepo 与之对齐。
        Map<String, Object> payload = taskService.payloadOf(task);
        String owner = str(payload.get("owner"), null);
        String repo = str(payload.get("repo"), null);
        Long createdBy = asLong(payload.get("createdBy"));
        if (!StringUtils.hasText(owner) || !StringUtils.hasText(repo) || createdBy == null) {
            // 刻意抛错而不是 return：删仓是不可逆动作，「没做成」必须显形，
            // 否则又是一次静默假成功（Generic 异常会被直接判 FAILED 并写 last_error）。
            throw new IllegalStateException("删除 " + props.providerLabel() + " 仓库缺少 owner/repo/createdBy，"
                    + "无法确认要删哪个仓库，已中止以免误删；task=" + task.getId());
        }
        String token = tokenService.requireAccessToken(task.getTenantId(), createdBy);
        try {
            client.deleteRepo(token, owner, repo);
        } catch (RepoProviderException e) {
            // 远端已不存在 = 目标已达成，不算失败（否则删项目会因 404 卡住）
            if (e.getStatus() == 404) {
                log.info("Gitee 仓库 {}/{} 已不存在，跳过删除", owner, repo);
                return;
            }
            throw e;
        }
        log.info("已删除 Gitee 仓库 {}/{}", owner, repo);
    }

    // ======================================================================
    // 工具
    // ======================================================================

    /**
     * 目标 owner（建仓 / 配 Webhook 的归属组织）。
     *
     * <p><b>优先级反转</b>（相对旧实现）：优先用项目落库时记录的 {@code giteeOwner}，
     * 仅在项目未记录时回落到「当前租户生效组织」。
     * 旧实现优先 {@code props.getOrg()}，在租户改了组织后会给<b>旧项目</b>的 Webhook
     * 错配到新组织——这是个真 bug。项目创建时已经把当时正确的组织写进了 {@code giteeOwner}，
     * 旧项目应继续待在它的旧组织里；新项目（改组织之后创建）落到新组织。</p>
     */
    String targetOwner(GiteeProject p) {
        String stored = p.getGiteeOwner();
        if (StringUtils.hasText(stored)) {
            return stored;
        }
        // 仅历史空值 / 新项目未记录时，回落到「当前租户生效组织」
        String resolved = tenantConfigService.effectiveOrg(p.getTenantId());
        return StringUtils.hasText(resolved) ? resolved : null;
    }

    /** 回调地址：必须能被托管方访问到（127.0.0.1 无效）。 */
    String callbackUrl(Long projectId) {
        String base = props.getWebhookBaseUrl();
        if (!StringUtils.hasText(base)) {
            throw new IllegalStateException("未配置 " + props.configKeyPrefix() + ".webhook-base-url，"
                    + props.providerLabel() + " 无法回调本机地址；请填写平台对 "
                    + props.providerLabel() + " 可见的公网地址");
        }
        return (base.endsWith("/") ? base.substring(0, base.length() - 1) : base)
                + "/api/v1/gitee/webhook/" + projectId;
    }

    private void markFailed(GiteeProject p, String error) {
        GiteeProject upd = new GiteeProject();
        upd.setId(p.getId());
        upd.setStatus(GiteeProject.STATUS_FAILED);
        upd.setErrorMsg(error == null ? "未知错误" : truncate(error));
        upd.setUpdatedAt(LocalDateTime.now());
        projectMapper.updateById(upd);
    }

    private static boolean isAlreadyExists(RepoProviderException e) {
        String m = e.getMessage() == null ? "" : e.getMessage().toLowerCase();
        return e.getStatus() == 422 || m.contains("already exists") || m.contains("已存在")
                || m.contains("have been taken") || m.contains("path has been used");
    }

    private static String randomSecret() {
        byte[] b = new byte[24];
        RANDOM.nextBytes(b);
        return HexFormat.of().formatHex(b);
    }

    private static String truncate(String s) {
        return s.length() > 500 ? s.substring(0, 500) : s;
    }

    /**
     * 仓库**网页**地址：取自 Gitee 响应的 {@code html_url}，**并剥掉结尾的 {@code .git}**。
     *
     * <p><b>为什么必须剥</b>：真站 Gitee 的 {@code html_url} 实测带后缀 ——
     * {@code https://gitee.com/{owner}/{repo}.git}（而本地桩返回的是不带后缀的形态）。
     * 平台的 {@code gitee_html_url} 被当作网页基址使用，最典型的是文件链接
     * （{@code GiteeContentService} 拼 {@code + "/blob/" + branch + "/" + path}）。
     * 不剥后缀就会拼出 {@code .../{repo}.git/blob/master/x.md} → **404**——
     * 而这一缺陷在桩环境下**永远不会出现**（桩不带 {@code .git}），故回归套件全绿也照样漏。</p>
     *
     * <p>对不带后缀的响应（桩 / 未来的 Gitee）是空操作。</p>
     */
    private static String webUrl(Map<String, Object> repo) {
        String s = str(repo.get("html_url"), null);
        if (s == null) {
            return null;
        }
        return s.endsWith(".git") ? s.substring(0, s.length() - 4) : s;
    }

    /**
     * HTTPS 克隆地址。
     *
     * <p><b>为什么要回落</b>：Gitee 的 repos 接口实测**不返回 {@code https_url}**（值为 null），
     * 只有 {@code html_url}（带 {@code .git}）与 {@code ssh_url}。直接取 {@code https_url}
     * 会让该列在真站上恒为 null，前端就少一个可用的克隆入口。
     * 这里按 {@code clone_url} → {@code https_url} → {@code html_url} 的顺序回落 ——
     * 桩返回 {@code https_url}，顺序保证了**桩下取值与历史完全一致**。</p>
     */
    private static String cloneUrl(Map<String, Object> repo) {
        String s = str(repo.get("clone_url"), null);
        if (s == null) {
            s = str(repo.get("https_url"), null);
        }
        if (s == null) {
            s = str(repo.get("html_url"), null);
        }
        return s;
    }

    private static String str(Object o, String dft) {
        if (o == null) {
            return dft;
        }
        String s = String.valueOf(o);
        return s.isBlank() ? dft : s;
    }

    private static Long asLong(Object o) {
        if (o == null) {
            return null;
        }
        try {
            return Long.parseLong(String.valueOf(o));
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
