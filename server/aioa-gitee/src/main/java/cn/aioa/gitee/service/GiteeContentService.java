package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.client.GiteeApiException;
import cn.aioa.gitee.client.GiteeClient;
import cn.aioa.gitee.entity.GiteeCommit;
import cn.aioa.gitee.entity.GiteeEvent;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.mapper.GiteeCommitMapper;
import cn.aioa.gitee.mapper.GiteeEventMapper;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 仓库内容服务：浏览（分支 / 目录 / 文件）与**网页上传提交**。
 *
 * <p><b>两条提交路径的差异在这里体现</b>：
 * ① 网页上传 —— 平台调 Gitee contents 接口写文件，**同步返回**，平台立刻知道 sha，
 *    因此写入后马上落 {@code gitee_commit(source=WEB)}；
 * ② 本地 git push —— 平台不知情，只能等 Webhook 回流，由 {@code GiteeWebhookService}
 *    落 {@code gitee_commit(source=GIT)}。两者共用同一张表、同一个唯一键，天然合流。</p>
 *
 * <p><b>浏览类接口为什么优先读本地库</b>：Gitee 有速率限制，每次翻页都打远端会让
 * 「项目详情页」这种高频页面把额度吃光。远端只用于「实时性要求高」的分支/文件树，
 * 提交与事件流一律读本地（Webhook 已经把它们同步过来了）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeContentService {

    /** 单文件上传上限：Gitee contents 接口不适合传大文件（大文件应走 git）。 */
    private static final int MAX_UPLOAD_BYTES = 512 * 1024;

    /** 事件流默认与最大页长。 */
    private static final int DEFAULT_PAGE_SIZE = 20;
    private static final int MAX_PAGE_SIZE = 100;

    private final GiteeProjectService projectService;
    private final GiteeTokenService tokenService;
    private final GiteeClient client;
    private final GiteeCommitMapper commitMapper;
    private final GiteeEventMapper eventMapper;

    // ======================================================================
    // 浏览
    // ======================================================================

    /**
     * 分支列表（远端实时）。
     *
     * <p>远端不可用时**降级为「默认分支」单元素**而不是抛错：限流是常态，
     * 让用户看到「至少有一个默认分支」比看到红色报错有用；同时在返回值里带
     * {@code degraded=true} 说明原因，不静默撒谎。</p>
     */
    public Map<String, Object> branches(AuthUser user, Long projectId) {
        GiteeProject p = projectService.requireVisible(user, projectId, false);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectId", p.getId());
        out.put("defaultBranch", p.getDefaultBranch());
        try {
            String token = tokenService.requireAccessTokenForProject(p);
            List<Map<String, Object>> raw = client.listBranches(token, p.getGiteeOwner(), p.getGiteeRepo());
            List<Map<String, Object>> items = new ArrayList<>();
            for (Map<String, Object> b : raw) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("name", b.get("name"));
                m.put("protected", b.get("protected"));
                Map<String, Object> commit = GiteeWebhookService.asMap(b.get("commit"));
                m.put("lastSha", shortSha(GiteeWebhookService.str(commit.get("sha"))));
                items.add(m);
            }
            out.put("items", items);
            out.put("total", items.size());
            out.put("degraded", false);
            return out;
        } catch (Exception e) {
            log.warn("分支列表降级（项目 {}）：{}", projectId, e.getMessage());
            out.put("items", StringUtils.hasText(p.getDefaultBranch())
                    ? List.of(Map.of("name", p.getDefaultBranch(), "degraded", true)) : List.of());
            out.put("total", StringUtils.hasText(p.getDefaultBranch()) ? 1 : 0);
            out.put("degraded", true);
            out.put("degradedReason", e.getMessage());
            return out;
        }
    }

    /**
     * 目录 / 文件内容。
     *
     * @param path 仓库内路径（空串表示根目录）
     * @param ref  分支 / tag / sha，空则默认分支
     */
    public Map<String, Object> contents(AuthUser user, Long projectId, String path, String ref) {
        GiteeProject p = projectService.requireVisible(user, projectId, false);
        String token = tokenService.requireAccessTokenForProject(p);
        String safeRef = StringUtils.hasText(ref) ? ref : p.getDefaultBranch();
        String safePath = normPath(path);
        Object raw = client.getContents(token, p.getGiteeOwner(), p.getGiteeRepo(), safePath, safeRef);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectId", p.getId());
        out.put("path", safePath);
        out.put("ref", safeRef);
        out.put("kind", raw instanceof List ? "dir" : "file");
        if (raw instanceof List<?> list) {
            List<Map<String, Object>> items = new ArrayList<>();
            for (Object o : list) {
                Map<String, Object> c = GiteeWebhookService.asMap(o);
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("name", c.get("name"));
                m.put("path", c.get("path"));
                m.put("type", c.get("type"));
                m.put("size", c.get("size"));
                m.put("sha", shortSha(GiteeWebhookService.str(c.get("sha"))));
                items.add(m);
            }
            out.put("items", items);
            out.put("total", items.size());
        } else {
            Map<String, Object> c = GiteeWebhookService.asMap(raw);
            out.put("name", c.get("name"));
            out.put("size", c.get("size"));
            out.put("sha", shortSha(GiteeWebhookService.str(c.get("sha"))));
            out.put("downloadUrl", c.get("download_url"));
            boolean binary = isBinary(c.get("encoding"), GiteeWebhookService.str(c.get("content")));
            out.put("binary", binary);
            // 二进制内容不返回正文（base64 塞进 JSON 没有意义，还会撑爆响应）
            out.put("text", binary ? null : decodeText(GiteeWebhookService.str(c.get("content"))));
            out.put("contentOmitted", binary);
        }
        return out;
    }

    /** 提交记录（本地库，Webhook + 网页上传两路合流）。 */
    public Map<String, Object> commits(AuthUser user, Long projectId, String branch, Integer page, Integer size) {
        GiteeProject p = projectService.requireVisible(user, projectId, false);
        int pg = page == null || page < 1 ? 1 : page;
        int sz = size == null || size < 1 ? DEFAULT_PAGE_SIZE : Math.min(size, MAX_PAGE_SIZE);

        LambdaQueryWrapper<GiteeCommit> q = new LambdaQueryWrapper<GiteeCommit>()
                .eq(GiteeCommit::getProjectId, p.getId())
                .orderByDesc(GiteeCommit::getId);
        if (StringUtils.hasText(branch)) {
            q.eq(GiteeCommit::getBranch, branch.trim());
        }
        Long total = commitMapper.selectCount(q.clone());
        List<GiteeCommit> rows = commitMapper.selectList(q
                .last("limit " + sz + " offset " + ((long) (pg - 1) * sz)));

        List<Map<String, Object>> items = new ArrayList<>();
        for (GiteeCommit c : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("sha", c.getSha());
            m.put("shortSha", shortSha(c.getSha()));
            m.put("branch", c.getBranch());
            m.put("message", c.getMessage());
            m.put("authorName", c.getAuthorName());
            m.put("authorEmail", c.getAuthorEmail());
            m.put("authorUserId", c.getAuthorUserId());
            m.put("source", c.getSource());
            m.put("committedAt", c.getCommittedAt());
            items.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectId", p.getId());
        out.put("items", items);
        out.put("total", total == null ? 0 : total);
        out.put("page", pg);
        out.put("size", sz);
        return out;
    }

    /** 事件流（本地库，Webhook 落库的原始事件）。 */
    public Map<String, Object> events(AuthUser user, Long projectId, String eventType, Integer page, Integer size) {
        GiteeProject p = projectService.requireVisible(user, projectId, false);
        int pg = page == null || page < 1 ? 1 : page;
        int sz = size == null || size < 1 ? DEFAULT_PAGE_SIZE : Math.min(size, MAX_PAGE_SIZE);

        LambdaQueryWrapper<GiteeEvent> q = new LambdaQueryWrapper<GiteeEvent>()
                .eq(GiteeEvent::getProjectId, p.getId())
                .orderByDesc(GiteeEvent::getId);
        if (StringUtils.hasText(eventType)) {
            q.eq(GiteeEvent::getEventType, eventType.trim().toUpperCase());
        }
        Long total = eventMapper.selectCount(q.clone());
        // payload 不入列表（可能几十 KB）；详情另有接口
        List<GiteeEvent> rows = eventMapper.selectList(
                q.select(GiteeEvent.class, f -> !"payload".equals(f.getColumn()))
                        .last("limit " + sz + " offset " + ((long) (pg - 1) * sz)));

        List<Map<String, Object>> items = new ArrayList<>();
        for (GiteeEvent e : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", e.getId());
            m.put("eventType", e.getEventType());
            m.put("giteeEvent", e.getGiteeEvent());
            m.put("action", e.getAction());
            m.put("title", e.getTitle());
            m.put("summary", e.getSummary());
            m.put("refName", e.getRefName());
            m.put("commitSha", e.getCommitSha());
            m.put("shortSha", shortSha(e.getCommitSha()));
            m.put("actorLogin", e.getActorLogin());
            m.put("actorGiteeUid", e.getActorGiteeUid());
            m.put("actorUserId", e.getActorUserId());
            // 身份映射是否成功，直接暴露给前端，避免前端再去猜
            m.put("actorMapped", e.getActorUserId() != null);
            m.put("occurredAt", e.getOccurredAt());
            m.put("receivedAt", e.getReceivedAt());
            items.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectId", p.getId());
        out.put("items", items);
        out.put("total", total == null ? 0 : total);
        out.put("page", pg);
        out.put("size", sz);
        return out;
    }

    // ======================================================================
    // 网页上传提交
    // ======================================================================

    /**
     * 网页上传文件（提交方式①）。
     *
     * <p><b>用「当前登录用户」的令牌而不是项目创建者的</b>：虽然写的是同一个仓库，
     * 但 Gitee 侧的提交作者取自令牌所属账号。用创建者令牌会让所有人的提交都变成
     * 「创建者提交」，审计上完全失效。</p>
     *
     * <p>权限双闸门：平台侧 {@code requireVisible(forWrite=true)} 管「谁能操作这个项目」，
     * Gitee 侧 collaborator 权限管「令牌能不能写进仓库」，两者都要过。</p>
     */
    public Map<String, Object> upload(AuthUser user, Long projectId, Map<String, Object> body) {
        GiteeProject p = projectService.requireVisible(user, projectId, true);
        String path = normPath(GiteeWebhookService.str(body == null ? null : body.get("path")));
        String content = GiteeWebhookService.str(body == null ? null : body.get("content"));
        if (!StringUtils.hasText(path)) {
            throw BizException.badRequest("请填写文件路径（如 docs/readme.md）");
        }
        if (content == null) {
            content = "";
        }
        byte[] bytes = content.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > MAX_UPLOAD_BYTES) {
            throw BizException.badRequest("文件内容超过 512KB，请改用 git push 提交大文件");
        }
        String message = GiteeWebhookService.str(body.get("message"));
        if (!StringUtils.hasText(message)) {
            message = "通过 AIOA 平台更新 " + path;
        }
        String branch = GiteeWebhookService.str(body.get("branch"));
        if (!StringUtils.hasText(branch)) {
            branch = p.getDefaultBranch();
        }

        String token = tokenService.requireAccessToken(p.getTenantId(), user.getUserId());
        String base64 = Base64.getEncoder().encodeToString(bytes);

        // 「新建」与「覆盖」在 Gitee 上是两个接口：POST 只能建新文件，对已存在的路径返回 422；
        // 覆盖必须 PUT 且带上该文件当前的 blob sha（服务端据此做并发冲突检测）。
        // 这里采用「先 POST，撞到已存在再 PUT」：新建是最常见路径，只花 1 次调用；
        // 覆盖多花 1 次失败的 POST，但换来「不需要前端先查一次 sha」的简单契约。
        Map<String, Object> resp;
        try {
            resp = client.putFile(token, p.getGiteeOwner(), p.getGiteeRepo(), path, base64, message, branch);
        } catch (GiteeApiException e) {
            if (!fileExistsError(e)) {
                throw e;
            }
            String existingSha = existingFileSha(token, p, path, branch);
            if (!StringUtils.hasText(existingSha)) {
                throw e;
            }
            log.info("文件已存在，改为覆盖提交 project={} path={} sha={}",
                    p.getId(), path, shortSha(existingSha));
            resp = client.updateFile(token, p.getGiteeOwner(), p.getGiteeRepo(),
                    path, base64, message, branch, existingSha);
        }

        // 落提交记录：contents 接口成功即产生一次提交，立刻可见，不必等 Webhook
        Map<String, Object> commit = GiteeWebhookService.asMap(resp.get("commit"));
        String sha = GiteeWebhookService.str(commit.get("sha"));
        if (!StringUtils.hasText(sha)) {
            sha = GiteeWebhookService.str(GiteeWebhookService.asMap(resp.get("content")).get("sha"));
        }
        Long commitId = null;
        if (StringUtils.hasText(sha)) {
            GiteeCommit gc = new GiteeCommit();
            gc.setTenantId(p.getTenantId());
            gc.setProjectId(p.getId());
            gc.setSha(sha);
            gc.setBranch(branch);
            gc.setMessage(GiteeWebhookService.firstLine(message));
            gc.setAuthorName(user.getNickname() == null ? user.getUsername() : user.getNickname());
            gc.setAuthorEmail(null);
            gc.setAuthorUserId(user.getUserId());
            gc.setSource(GiteeCommit.SOURCE_WEB);
            gc.setCommittedAt(LocalDateTime.now());
            gc.setCreatedAt(LocalDateTime.now());
            try {
                commitMapper.insert(gc);
                commitId = gc.getId();
            } catch (org.springframework.dao.DuplicateKeyException dup) {
                // 同一 sha 已被 push 事件记录（极端抢跑），忽略
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectId", p.getId());
        out.put("path", path);
        out.put("branch", branch);
        out.put("sha", sha);
        out.put("shortSha", shortSha(sha));
        out.put("commitId", commitId);
        out.put("source", GiteeCommit.SOURCE_WEB);
        // 前端可以直接拿这个链接跳过去看 diff
        out.put("htmlUrl", p.getGiteeHtmlUrl() == null ? null
                : p.getGiteeHtmlUrl() + "/blob/" + branch + "/" + path);
        return out;
    }

    // ======================================================================
    // 工具
    // ======================================================================

    /** 是否是「文件已存在」类错误（应当改为覆盖提交）。 */
    static boolean fileExistsError(GiteeApiException e) {
        if (e.getStatus() == 422) {
            return true;
        }
        String m = e.getMessage() == null ? "" : e.getMessage().toLowerCase(Locale.ROOT);
        return m.contains("already exists") || m.contains("已存在") || m.contains("blob sha");
    }

    /** 取文件当前的 blob sha（覆盖提交必需）。取不到就返回 null，由调用方决定是否放弃。 */
    private String existingFileSha(String token, GiteeProject p, String path, String ref) {
        try {
            Map<String, Object> c = GiteeWebhookService.asMap(
                    client.getContents(token, p.getGiteeOwner(), p.getGiteeRepo(), path, ref));
            return GiteeWebhookService.str(c.get("sha"));
        } catch (Exception e) {
            log.warn("读取现有文件 sha 失败 project={} path={}：{}", p.getId(), path, e.getMessage());
            return null;
        }
    }

    /** 归一化仓库路径：去掉首尾斜杠与 {@code ..} 片段（避免越权访问仓库外内容）。 */
    static String normPath(String path) {
        if (!StringUtils.hasText(path)) {
            return "";
        }
        String s = path.trim().replace('\\', '/');
        while (s.startsWith("/")) {
            s = s.substring(1);
        }
        while (s.endsWith("/")) {
            s = s.substring(0, s.length() - 1);
        }
        List<String> parts = new ArrayList<>();
        for (String seg : s.split("/")) {
            if (seg.isEmpty() || ".".equals(seg)) {
                continue;
            }
            if ("..".equals(seg)) {
                throw BizException.badRequest("非法路径：不允许使用 .. 跳出仓库目录");
            }
            parts.add(seg);
        }
        return String.join("/", parts);
    }

    static String shortSha(String sha) {
        return sha == null ? null : sha.substring(0, Math.min(7, sha.length()));
    }

    /** 只有 base64 且看起来不像纯文本时才当二进制（Gitee 对文本也会返回 base64）。 */
    static boolean isBinary(Object encoding, String content) {
        if (!"base64".equalsIgnoreCase(GiteeWebhookService.str(encoding))) {
            return false;
        }
        if (!StringUtils.hasText(content)) {
            return false;
        }
        try {
            byte[] raw = Base64.getMimeDecoder().decode(content);
            int probe = Math.min(raw.length, 4096);
            for (int i = 0; i < probe; i++) {
                if (raw[i] == 0) {
                    return true;
                }
            }
            return false;
        } catch (IllegalArgumentException e) {
            return false;
        }
    }

    static String decodeText(String content) {
        if (!StringUtils.hasText(content)) {
            return "";
        }
        try {
            return new String(Base64.getMimeDecoder().decode(content), StandardCharsets.UTF_8);
        } catch (IllegalArgumentException e) {
            // 不是 base64 就当成已解码文本返回
            return content;
        }
    }
}
