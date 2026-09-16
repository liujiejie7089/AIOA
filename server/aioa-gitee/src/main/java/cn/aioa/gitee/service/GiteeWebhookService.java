package cn.aioa.gitee.service;

import cn.aioa.gitee.entity.GiteeAccount;
import cn.aioa.gitee.entity.GiteeCommit;
import cn.aioa.gitee.entity.GiteeEvent;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.mapper.GiteeCommitMapper;
import cn.aioa.gitee.mapper.GiteeEventMapper;
import cn.aioa.gitee.mapper.GiteeProjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Gitee Webhook 接收与落库。
 *
 * <p><b>与 GitHub 最容易搞混的一点</b>：Gitee 不做 HMAC 签名，而是把创建 Webhook 时
 * 填的 {@code password} 以**明文**放在请求头 {@code X-Gitee-Token} 里回传。
 * 因此校验方式就是常量时间字符串比对 —— 不要试图去算 sha256 签名，那样永远不匹配。</p>
 *
 * <p><b>幂等为什么用「业务键 + 唯一索引」而不是先查后插</b>：先查后插在并发投递下会
 * 双写（两个请求同时查到「不存在」）。唯一索引是数据库级的最终防线，捕获
 * {@link DuplicateKeyException} 即判定重复，语义简单且并发安全。</p>
 *
 * <p><b>为什么必须快速返回</b>：Webhook 超时会被 Gitee 重投。这里只做「校验 + 落库」，
 * 任何出网调用（如反查仓库详情）都不放在这条链路上。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeWebhookService {

    /** 原始报文入库上限：JSON 列够大，但没必要把 200 个 commit 的报文整条塞进去。 */
    private static final int MAX_PAYLOAD_CHARS = 60000;

    /** push 事件落 commit 明细的上限，避免一次 push 打爆写库。 */
    private static final int MAX_COMMITS_PER_PUSH = 20;

    private final GiteeProjectMapper projectMapper;
    private final GiteeEventMapper eventMapper;
    private final GiteeCommitMapper commitMapper;
    private final GiteeTokenService tokenService;
    private final ObjectMapper objectMapper;

    /**
     * 处理一次 Webhook 投递。
     *
     * @param projectId    路径参数：平台项目 id（Webhook 地址由平台生成，形如 /api/v1/gitee/webhook/{id}）
     * @param eventHeader  {@code X-Gitee-Event}
     * @param tokenHeader  {@code X-Gitee-Token}（明文共享密钥）
     * @param requestId    {@code X-Gitee-Request-Id}（有则用，无则留空）
     * @param rawBody      原始报文（用于计算兜底幂等键）
     * @return 处理结果（含 duplicated 标记，便于对账）
     */
    public Map<String, Object> handle(Long projectId, String eventHeader, String tokenHeader,
                                      String requestId, String rawBody) {
        Map<String, Object> out = new LinkedHashMap<>();
        GiteeProject p = projectMapper.selectById(projectId);
        if (p == null) {
            // 不区分「不存在」与「已删除」：Webhook 来自外部，不泄露内部状态
            log.warn("Webhook 命中未知项目 id={}", projectId);
            out.put("accepted", false);
            out.put("reason", "PROJECT_NOT_FOUND");
            return out;
        }
        if (!secretMatches(p, tokenHeader)) {
            // 只记 id，不记密钥内容
            log.warn("Webhook 密钥不匹配 project={}", projectId);
            out.put("accepted", false);
            out.put("reason", "BAD_TOKEN");
            return out;
        }

        Map<String, Object> body = parse(rawBody);
        String giteeEvent = eventHeader == null ? "" : eventHeader.trim();
        String eventKey = buildEventKey(giteeEvent, body, rawBody);

        GiteeEvent ev = new GiteeEvent();
        ev.setTenantId(p.getTenantId());
        ev.setProjectId(p.getId());
        ev.setEventType(classify(giteeEvent));
        ev.setGiteeEvent(StringUtils.hasText(giteeEvent) ? trunc(giteeEvent, 64) : null);
        ev.setEventKey(eventKey);
        ev.setRequestId(trunc(requestId, 64));
        ev.setPayload(trunc(rawBody, MAX_PAYLOAD_CHARS));
        ev.setReceivedAt(LocalDateTime.now());

        Map<String, Object> repository = asMap(body.get("repository"));
        Map<String, Object> sender = asMap(body.get("sender"));

        // ---- 身份映射：gitee uid 优先，登录名兜底 ----
        Long actorUid = asLong(sender.get("id"));
        String actorLogin = str(sender.get("login"));
        ev.setActorGiteeUid(actorUid);
        ev.setActorLogin(trunc(actorLogin, 128));
        ev.setActorUserId(resolvePlatformUser(p.getTenantId(), actorUid, actorLogin));

        // ---- 按事件类型抽取可读字段 ----
        switch (ev.getEventType()) {
            case GiteeEvent.TYPE_PUSH -> fillPush(ev, body, repository);
            case GiteeEvent.TYPE_MERGE_REQUEST -> fillMergeRequest(ev, body);
            case GiteeEvent.TYPE_ISSUE -> fillIssue(ev, body);
            case GiteeEvent.TYPE_NOTE -> fillNote(ev, body);
            default -> {
                ev.setSummary(trunc("收到事件：" + giteeEvent, 1024));
                ev.setOccurredAt(parseTime(body.get("created_at")));
            }
        }

        try {
            eventMapper.insert(ev);
        } catch (DuplicateKeyException dup) {
            // 幂等命中：Gitee 重投同一事件。这是**正常路径**，不是错误。
            log.debug("Webhook 重复投递已丢弃 project={} key={}", projectId, eventKey);
            out.put("accepted", true);
            out.put("duplicated", true);
            out.put("eventKey", eventKey);
            // 重复路径也回 commits=0：字段集与首次投递保持一致，
            // 否则调用方（含测试与第三方对账脚本）要处理「键时有时无」。
            out.put("commits", 0);
            return out;
        }

        // push 事件顺带落 commit 明细（网页上传路径由 GiteeContentService 自己写）
        int newCommits = 0;
        if (GiteeEvent.TYPE_PUSH.equals(ev.getEventType())) {
            newCommits = savePushCommits(p, ev, body);
        }

        out.put("accepted", true);
        out.put("duplicated", false);
        out.put("eventId", ev.getId());
        out.put("eventType", ev.getEventType());
        out.put("eventKey", eventKey);
        out.put("commits", newCommits);
        return out;
    }

    // ======================================================================
    // 校验
    // ======================================================================

    /**
     * 常量时间比对 Webhook 密钥。
     *
     * <p>项目未配置密钥（历史数据/create 失败）时**拒绝**而不是放行：
     * Webhook 是写入口，放行等于允许任意人伪造提交记录。</p>
     */
    private boolean secretMatches(GiteeProject p, String tokenHeader) {
        String expected = p.getWebhookSecret();
        if (!StringUtils.hasText(expected)) {
            return false;
        }
        String actual = tokenHeader == null ? "" : tokenHeader.trim();
        return MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.UTF_8),
                actual.getBytes(StandardCharsets.UTF_8));
    }

    /** 事件类型归一化：把 Gitee 的事件头映射为平台枚举。 */
    static String classify(String eventHeader) {
        String e = eventHeader == null ? "" : eventHeader.toLowerCase();
        if (e.contains("push")) {
            return GiteeEvent.TYPE_PUSH;
        }
        if (e.contains("merge request") || e.contains("pull request")) {
            return GiteeEvent.TYPE_MERGE_REQUEST;
        }
        if (e.contains("issue")) {
            return GiteeEvent.TYPE_ISSUE;
        }
        if (e.contains("note")) {
            return GiteeEvent.TYPE_NOTE;
        }
        return GiteeEvent.TYPE_OTHER;
    }

    /**
     * 构造幂等键。
     *
     * <p>优先用**事件自身的稳定标识**（Gitee 重投时这些字段不变），只有在都取不到时
     * 才退化为整报文哈希 —— 整报文哈希的问题是同一次业务动作若报文含时间戳微差
     * 就会重复入库，所以它只是兜底。</p>
     */
    static String buildEventKey(String giteeEvent, Map<String, Object> body, String rawBody) {
        String type = classify(giteeEvent);
        String part = switch (type) {
            case GiteeEvent.TYPE_PUSH -> {
                String after = str(body.get("after"));
                yield StringUtils.hasText(after) ? after : str(asMap(body.get("head_commit")).get("id"));
            }
            case GiteeEvent.TYPE_MERGE_REQUEST -> {
                Map<String, Object> pr = asMap(body.get("pull_request"));
                yield str(pr.get("id")) + "-" + str(body.get("action")) + "-" + str(pr.get("updated_at"));
            }
            case GiteeEvent.TYPE_ISSUE -> {
                Map<String, Object> is = asMap(body.get("issue"));
                yield str(is.get("id")) + "-" + str(body.get("action")) + "-" + str(is.get("updated_at"));
            }
            case GiteeEvent.TYPE_NOTE -> {
                Map<String, Object> c = asMap(body.get("comment"));
                yield str(c.get("id")) + "-" + str(body.get("action"));
            }
            default -> str(str(body.get("created_at")) + str(asMap(body.get("repository")).get("id")));
        };
        if (!StringUtils.hasText(part) || "nullnull".equals(part)) {
            part = "body:" + sha256(rawBody);
        }
        return type + ":" + sha256(giteeEvent + "|" + part);
    }

    // ======================================================================
    // 事件字段填充
    // ======================================================================

    private void fillPush(GiteeEvent ev, Map<String, Object> body, Map<String, Object> repository) {
        String ref = str(body.get("ref"));
        ev.setRefName(trunc(shortRef(ref), 255));
        ev.setCommitSha(trunc(str(body.get("after")), 64));
        Map<String, Object> head = asMap(body.get("head_commit"));
        if (head.isEmpty()) {
            List<Map<String, Object>> commits = asListOfMap(body.get("commits"));
            if (!commits.isEmpty()) {
                head = commits.get(commits.size() - 1);
            }
        }
        String msg = firstLine(str(head.get("message")));
        String who = str(asMap(head.get("author")).get("name"));
        String repo = str(repository.get("full_name"));
        ev.setAction("push");
        ev.setTitle(trunc(msg == null ? "推送提交" : msg, 512));
        ev.setSummary(trunc(String.format("%s 向 %s 推送了 %d 个提交%s",
                who == null ? "某成员" : who,
                shortRef(ref),
                asListOfMap(body.get("commits")).size(),
                repo == null ? "" : "（" + repo + "）"), 1024));
        ev.setOccurredAt(parseTime(head.get("timestamp")));
    }

    private void fillMergeRequest(GiteeEvent ev, Map<String, Object> body) {
        Map<String, Object> pr = asMap(body.get("pull_request"));
        String action = str(body.get("action"));
        ev.setAction(trunc(action, 32));
        ev.setTitle(trunc(str(pr.get("title")), 512));
        ev.setRefName(trunc(str(asMap(pr.get("base")).get("ref")), 255));
        ev.setSummary(trunc(String.format("合并请求 #%s「%s」%s，%s → %s",
                str(pr.get("number")),
                str(pr.get("title")),
                actionText(action),
                str(asMap(pr.get("head")).get("ref")),
                str(asMap(pr.get("base")).get("ref"))), 1024));
        ev.setOccurredAt(parseTime(pr.get("updated_at")));
    }

    private void fillIssue(GiteeEvent ev, Map<String, Object> body) {
        Map<String, Object> issue = asMap(body.get("issue"));
        String action = str(body.get("action"));
        ev.setAction(trunc(action, 32));
        ev.setTitle(trunc(str(issue.get("title")), 512));
        ev.setSummary(trunc(String.format("任务 #%s「%s」%s",
                str(issue.get("number")), str(issue.get("title")), actionText(action)), 1024));
        ev.setOccurredAt(parseTime(issue.get("updated_at")));
    }

    private void fillNote(GiteeEvent ev, Map<String, Object> body) {
        Map<String, Object> comment = asMap(body.get("comment"));
        String action = str(body.get("action"));
        ev.setAction(trunc(StringUtils.hasText(action) ? action : "comment", 32));
        String target = noteTarget(body);
        ev.setTitle(trunc(StringUtils.hasText(target) ? "评论：" + target : "新评论", 512));
        ev.setSummary(trunc(firstLine(str(comment.get("body"))), 1024));
        ev.setOccurredAt(parseTime(comment.get("created_at")));
        // 评论挂在 PR / Issue 上时，记录被评论对象的分支，便于前端跳转
        Map<String, Object> pr = asMap(body.get("pull_request"));
        if (!pr.isEmpty()) {
            ev.setRefName(trunc(str(asMap(pr.get("base")).get("ref")), 255));
        }
    }

    /** 评论对象描述：Issue 标题 / PR 标题 / commit sha。 */
    private String noteTarget(Map<String, Object> body) {
        Map<String, Object> issue = asMap(body.get("issue"));
        if (!issue.isEmpty()) {
            return "任务 #" + str(issue.get("number"));
        }
        Map<String, Object> pr = asMap(body.get("pull_request"));
        if (!pr.isEmpty()) {
            return "合并请求 #" + str(pr.get("number"));
        }
        String sha = str(body.get("commit"));
        return StringUtils.hasText(sha) ? "提交 " + sha.substring(0, Math.min(7, sha.length())) : null;
    }

    // ======================================================================
    // 提交明细（push）
    // ======================================================================

    /**
     * push 事件落提交明细。
     *
     * <p>唯一键 {@code (project_id, sha)} 已存在时跳过而不是报错 ——
     * 同一个 commit 可能先被网页上传路径记录，再由 push 回流，两路合一只留一条。</p>
     */
    private int savePushCommits(GiteeProject p, GiteeEvent ev, Map<String, Object> body) {
        List<Map<String, Object>> commits = asListOfMap(body.get("commits"));
        String branch = shortRef(str(body.get("ref")));
        int n = 0;
        int limit = Math.min(commits.size(), MAX_COMMITS_PER_PUSH);
        for (int i = 0; i < limit; i++) {
            Map<String, Object> c = commits.get(i);
            String sha = str(c.get("id"));
            if (!StringUtils.hasText(sha)) {
                sha = str(c.get("sha"));
            }
            if (!StringUtils.hasText(sha)) {
                continue;
            }
            Long exists = commitMapper.selectCount(new LambdaQueryWrapper<GiteeCommit>()
                    .eq(GiteeCommit::getProjectId, p.getId())
                    .eq(GiteeCommit::getSha, sha));
            if (exists != null && exists > 0) {
                continue;
            }
            Map<String, Object> author = asMap(c.get("author"));
            GiteeCommit gc = new GiteeCommit();
            gc.setTenantId(p.getTenantId());
            gc.setProjectId(p.getId());
            gc.setSha(trunc(sha, 64));
            gc.setBranch(trunc(branch, 128));
            gc.setMessage(trunc(firstLine(str(c.get("message"))), 1024));
            gc.setAuthorName(trunc(str(author.get("name")), 128));
            gc.setAuthorEmail(trunc(str(author.get("email")), 190));
            gc.setGiteeUid(ev.getActorGiteeUid());
            gc.setAuthorUserId(ev.getActorUserId());
            gc.setSource(GiteeCommit.SOURCE_GIT);
            gc.setEventId(ev.getId());
            gc.setCommittedAt(parseTime(c.get("timestamp")));
            gc.setCreatedAt(LocalDateTime.now());
            try {
                commitMapper.insert(gc);
                n++;
            } catch (DuplicateKeyException dup) {
                // 并发投递下唯一键兜底，忽略
            }
        }
        return n;
    }

    // ======================================================================
    // 身份映射
    // ======================================================================

    /**
     * Gitee 身份 → 平台用户。
     *
     * <p>只认**已绑定**的账号：没绑定的 Gitee 用户（例如外部协作者）落 NULL，
     * 前端展示 Gitee 登录名即可。不要用邮箱/昵称做模糊匹配 —— 那会把不同人串成一个人。</p>
     */
    private Long resolvePlatformUser(Long tenantId, Long giteeUid, String login) {
        GiteeAccount acc = tokenService.findByGiteeUid(tenantId, giteeUid);
        if (acc == null && StringUtils.hasText(login)) {
            acc = tokenService.findByUsername(tenantId, login);
        }
        return acc == null ? null : acc.getUserId();
    }

    // ======================================================================
    // 工具
    // ======================================================================

    private Map<String, Object> parse(String rawBody) {
        if (!StringUtils.hasText(rawBody)) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(rawBody, new com.fasterxml.jackson.core.type.TypeReference<>() {
            });
        } catch (Exception e) {
            log.warn("Webhook 报文不是合法 JSON，按空报文处理：{}", e.getMessage());
            return Map.of();
        }
    }

    static String sha256(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest((s == null ? "" : s).getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(d.length * 2);
            for (byte b : d) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception e) {
            // SHA-256 是 JDK 必备算法，走到这里说明环境异常；退化为 hashCode 避免整个回调 500
            return Integer.toHexString((s == null ? "" : s).hashCode());
        }
    }

    static String shortRef(String ref) {
        if (!StringUtils.hasText(ref)) {
            return null;
        }
        return ref.startsWith("refs/heads/") ? ref.substring("refs/heads/".length())
                : ref.startsWith("refs/tags/") ? ref.substring("refs/tags/".length()) : ref;
    }

    static String actionText(String action) {
        if (action == null) {
            return "更新";
        }
        return switch (action.toLowerCase()) {
            case "open", "opened" -> "被创建";
            case "close", "closed" -> "被关闭";
            case "reopen", "reopened" -> "被重新打开";
            case "merge", "merged" -> "被合并";
            case "update", "updated" -> "被更新";
            default -> action;
        };
    }

    /** 只取首行：提交信息多行时列表展示会很难看。 */
    static String firstLine(String s) {
        if (s == null) {
            return null;
        }
        int i = s.indexOf('\n');
        return (i < 0 ? s : s.substring(0, i)).trim();
    }

    static String trunc(String s, int max) {
        if (s == null) {
            return null;
        }
        String v = s.trim();
        return v.length() <= max ? v : v.substring(0, max);
    }

    static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    static Long asLong(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.valueOf(String.valueOf(o).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : Map.of();
    }

    @SuppressWarnings("unchecked")
    static List<Map<String, Object>> asListOfMap(Object o) {
        if (!(o instanceof List<?> l)) {
            return List.of();
        }
        return l.stream().filter(Map.class::isInstance).map(i -> (Map<String, Object>) i).toList();
    }

    /** Gitee 时间形如 {@code 2024-01-01T12:00:00+08:00} 或 {@code 2024-01-01 12:00:00}。 */
    static LocalDateTime parseTime(Object o) {
        String s = str(o);
        if (!StringUtils.hasText(s)) {
            return null;
        }
        try {
            return OffsetDateTime.parse(s).toLocalDateTime();
        } catch (DateTimeParseException ignored) {
            // 继续尝试无时区格式
        }
        try {
            return LocalDateTime.parse(s.replace(' ', 'T'));
        } catch (DateTimeParseException ignored) {
            return null;
        }
    }
}
