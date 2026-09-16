package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.entity.GiteeAccount;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.entity.GiteeRepoMember;
import cn.aioa.gitee.entity.GiteeTask;
import cn.aioa.gitee.mapper.GiteeRepoMemberMapper;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

/**
 * 项目成员管理：平台增删成员 → 自动同步到 Gitee 仓库权限。
 *
 * <p><b>为什么成员表按 giteeUsername 记账而不是 userId</b>：Gitee 的协作者接口认登录名，
 * 且成员可能在**还没绑定 Gitee** 时就被加进项目。此时记录 `syncStatus=PENDING`，
 * 等其完成绑定后由定时校准任务自动补推权限 —— 而不是直接拒绝「请他先绑定」，
 * 因为管理员本来就应该能先把人加进来。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeMemberService {

    private final GiteeRepoMemberMapper memberMapper;
    private final GiteeProjectService projectService;
    private final GiteeTokenService tokenService;
    private final GiteeTaskService taskService;
    private final OrgMemberMapper orgMemberMapper;
    private final cn.aioa.gitee.client.GiteeClient client;

    // ======================================================================
    // 增删
    // ======================================================================

    /**
     * 添加项目成员并排同步任务。
     *
     * <p><b>成员尚未绑定 Gitee 时 gitee_username 必须留 NULL</b>，不能用
     * {@code user-<id>} 之类的占位名 —— 占位名会一路传到
     * {@code PUT /collaborators/{username}}，变成一个**真实存在或不存在的外部用户**
     * 被拉进仓库（或产生一串 404 重试）。留 NULL 时同步处理器会识别出「还没绑定」
     * 并原地打回 PENDING，等绑定后由校准补齐。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public GiteeRepoMember add(AuthUser user, Long projectId, Map<String, Object> body) {
        GiteeProject p = projectService.requireVisible(user, projectId, true);

        Long userId = asLong(body.get("userId"));
        String giteeUsername = trim(body.get("giteeUsername"));
        String role = normalizeRole(body.get("role"));

        if (userId == null && !StringUtils.hasText(giteeUsername)) {
            throw BizException.badRequest("请选择平台成员，或直接填写 Gitee 登录名");
        }

        // 平台成员：取其绑定信息；未绑定则留 NULL（PENDING），绑定后由校准补齐
        GiteeAccount acc = null;
        if (userId != null) {
            acc = tokenService.findAccount(p.getTenantId(), userId);
            if (acc != null) {
                giteeUsername = acc.getGiteeUsername();
            }
        } else {
            acc = findByUsername(p.getTenantId(), giteeUsername);
        }

        // 去重键：有平台用户按 user_id 认（同一个人在改绑 Gitee 后不应变成两条成员）；
        // 否则按 Gitee 登录名认（外部协作者）。
        LambdaQueryWrapper<GiteeRepoMember> q = new LambdaQueryWrapper<GiteeRepoMember>()
                .eq(GiteeRepoMember::getProjectId, projectId);
        if (userId != null) {
            q.eq(GiteeRepoMember::getUserId, userId);
        } else {
            q.eq(GiteeRepoMember::getGiteeUsername, giteeUsername);
        }
        GiteeRepoMember exist = memberMapper.selectOne(q.last("limit 1"));
        if (exist != null) {
            // 已存在 → 更新角色/登录名（幂等），不新建
            GiteeRepoMember upd = new GiteeRepoMember();
            upd.setId(exist.getId());
            upd.setRole(role);
            upd.setUserId(userId == null ? exist.getUserId() : userId);
            if (acc != null) {
                upd.setGiteeUsername(acc.getGiteeUsername());
                upd.setGiteeUid(acc.getGiteeUid());
                upd.setLastError(null);
            }
            upd.setSyncStatus(GiteeRepoMember.SYNC_PENDING);
            upd.setUpdatedAt(LocalDateTime.now());
            memberMapper.updateById(upd);
            enqueueSync(p, exist.getId());
            return memberMapper.selectById(exist.getId());
        }

        GiteeRepoMember m = new GiteeRepoMember();
        m.setTenantId(p.getTenantId());
        m.setProjectId(projectId);
        m.setUserId(userId);
        m.setGiteeUid(acc == null ? null : acc.getGiteeUid());
        m.setGiteeUsername(acc == null ? null : acc.getGiteeUsername());
        m.setRole(role);
        m.setSource(GiteeRepoMember.SOURCE_PLATFORM);
        m.setSyncStatus(GiteeRepoMember.SYNC_PENDING);
        if (acc == null) {
            m.setLastError("成员尚未绑定 Gitee 账号，待绑定后自动同步权限");
        }
        m.setCreatedAt(LocalDateTime.now());
        memberMapper.insert(m);

        enqueueSync(p, m.getId());
        return m;
    }

    /**
     * 确保**项目创建者**是本仓库的管理员成员。
     *
     * <p>为什么必须做这件事：仓库建在组织下，创建者并不自动拿到仓库权限；若不补这一条，
     * 就会出现「他自己建的项目，点开仓库却无权访问」的荒谬状态，而且后续所有
     * 以创建者身份发起的同步（令牌取自创建者）也没有协作者身份支撑。</p>
     *
     * <p>为什么放在「仓库就绪之后」调用而不是建项目时：建仓之前排成员同步会打在
     * 一个还不存在的仓库上，Gitee 返回 404 → 被判定为永久失败 → 白烧一次重试预算。</p>
     *
     * <p>幂等：已有该用户的成员记录时只补齐角色与实际登录名，不新建第二条。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public void ensureCreatorMember(GiteeProject p) {
        Long creator = p.getCreatedBy();
        if (creator == null) {
            return;
        }
        GiteeAccount acc = tokenService.findAccount(p.getTenantId(), creator);
        GiteeRepoMember exist = memberMapper.selectOne(new LambdaQueryWrapper<GiteeRepoMember>()
                .eq(GiteeRepoMember::getProjectId, p.getId())
                .eq(GiteeRepoMember::getUserId, creator)
                .last("limit 1"));
        if (exist != null) {
            // 已存在：仅在其角色不是 ADMIN 或登录名缺失时补齐（避免无意义地反复入队）
            boolean needFix = !GiteeRepoMember.ROLE_ADMIN.equals(exist.getRole())
                    || (acc != null && !StringUtils.hasText(exist.getGiteeUsername()));
            if (!needFix && GiteeRepoMember.SYNC_SYNCED.equals(exist.getSyncStatus())) {
                return;
            }
            GiteeRepoMember upd = new GiteeRepoMember();
            upd.setId(exist.getId());
            upd.setRole(GiteeRepoMember.ROLE_ADMIN);
            if (acc != null) {
                upd.setGiteeUsername(acc.getGiteeUsername());
                upd.setGiteeUid(acc.getGiteeUid());
            }
            upd.setUpdatedAt(LocalDateTime.now());
            memberMapper.updateById(upd);
            enqueueSync(p, exist.getId());
            return;
        }

        GiteeRepoMember m = new GiteeRepoMember();
        m.setTenantId(p.getTenantId());
        m.setProjectId(p.getId());
        m.setUserId(creator);
        m.setGiteeUid(acc == null ? null : acc.getGiteeUid());
        m.setGiteeUsername(acc == null ? null : acc.getGiteeUsername());
        m.setRole(GiteeRepoMember.ROLE_ADMIN);
        m.setSource(GiteeRepoMember.SOURCE_PLATFORM);
        m.setSyncStatus(GiteeRepoMember.SYNC_PENDING);
        if (acc == null) {
            m.setLastError("项目创建者尚未绑定 Gitee 账号，待绑定后自动补齐仓库权限");
        }
        m.setCreatedAt(LocalDateTime.now());
        memberMapper.insert(m);
        enqueueSync(p, m.getId());
        log.info("项目 {} 创建者 {} 已登记为仓库管理员成员", p.getId(), creator);
    }

    /** 移除项目成员（软删 + 排同步任务）。 */
    @Transactional(rollbackFor = Exception.class)
    public void remove(AuthUser user, Long projectId, Long memberId) {
        GiteeProject p = projectService.requireVisible(user, projectId, true);
        GiteeRepoMember m = memberMapper.selectById(memberId);
        if (m == null || !Objects.equals(m.getProjectId(), projectId)) {
            throw BizException.notFound("成员记录不存在");
        }
        // 不允许把项目创建者踢出（否则没人能再管理这个仓库）
        if (PermissionCatalogCreatorGuard.isCreator(p, m)) {
            throw BizException.badRequest("项目创建者的仓库权限不可移除");
        }
        enqueueSync(p, memberId, GiteeMemberTaskHandler.OP_REMOVE);
    }

    /** 列出成员。 */
    public List<GiteeRepoMember> list(Long projectId) {
        return memberMapper.selectList(new LambdaQueryWrapper<GiteeRepoMember>()
                .eq(GiteeRepoMember::getProjectId, projectId)
                .orderByAsc(GiteeRepoMember::getId));
    }

    /**
     * 带可见性校验的成员列表（供接口层使用）。
     *
     * <p>把校验收进服务而不是让控制器自己先调一次 {@code requireVisible}：
     * 接口层漏掉一次校验就是一个越权读漏洞，收进来只有一处需要保证。</p>
     */
    public List<Map<String, Object>> listForUser(AuthUser user, Long projectId) {
        projectService.requireVisible(user, projectId, false);
        List<Map<String, Object>> out = new ArrayList<>();
        for (GiteeRepoMember m : list(projectId)) {
            out.add(toView(m));
        }
        return out;
    }

    /** 成员脱敏视图（成员表本身不含密钥，但仍显式列举字段以稳定接口契约）。 */
    public Map<String, Object> toView(GiteeRepoMember m) {
        Map<String, Object> x = new LinkedHashMap<>();
        x.put("id", m.getId());
        x.put("projectId", m.getProjectId());
        x.put("userId", m.getUserId());
        x.put("giteeUid", m.getGiteeUid());
        x.put("giteeUsername", m.getGiteeUsername());
        x.put("role", m.getRole());
        x.put("source", m.getSource());
        x.put("syncStatus", m.getSyncStatus());
        x.put("lastError", m.getLastError());
        x.put("syncedAt", m.getSyncedAt());
        x.put("createdAt", m.getCreatedAt());
        x.put("external", GiteeRepoMember.SOURCE_GITEE.equals(m.getSource()));
        return x;
    }

    /**
     * 可添加的成员候选。
     *
     * <p><b>候选口径</b>：本租户内**已绑定 Gitee** 的成员 —— 只有这样的人才可能被
     * Gitee 接受为协作者（协作者接口认登录名）。未绑定的人不是不能加，而是加进去
     * 只会停在 PENDING；因此这里只返回可立即生效的人，避免管理员加了半天没反应。</p>
     *
     * <p>返回值同时标注 {@code alreadyMember}，让前端一次请求就能渲染「可添加 / 已加入」，
     * 不必再查一次成员列表。</p>
     */
    public List<Map<String, Object>> candidates(AuthUser user, Long projectId, String keyword) {
        GiteeProject p = projectService.requireVisible(user, projectId, false);

        Map<Long, GiteeAccount> boundByUser = new LinkedHashMap<>();
        for (GiteeAccount a : tokenService.allAccounts(p.getTenantId())) {
            if (a.getUserId() != null) {
                boundByUser.put(a.getUserId(), a);
            }
        }
        Map<Long, GiteeRepoMember> memberByUser = new LinkedHashMap<>();
        for (GiteeRepoMember m : list(projectId)) {
            if (m.getUserId() != null) {
                memberByUser.put(m.getUserId(), m);
            }
        }

        String kw = StringUtils.hasText(keyword) ? keyword.trim().toLowerCase(Locale.ROOT) : null;
        List<Map<String, Object>> out = new ArrayList<>();
        if (!boundByUser.isEmpty()) {
            List<OrgMember> rows = orgMemberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                    .eq(OrgMember::getTenantId, p.getTenantId())
                    .in(OrgMember::getUserId, boundByUser.keySet())
                    .orderByAsc(OrgMember::getDepartmentId)
                    .orderByAsc(OrgMember::getId));
            for (OrgMember om : rows) {
                GiteeAccount acc = boundByUser.get(om.getUserId());
                if (acc == null) {
                    continue;
                }
                if (kw != null && !matches(kw, om.getName(), acc.getGiteeUsername(), om.getEmployeeNo())) {
                    continue;
                }
                GiteeRepoMember exist = memberByUser.get(om.getUserId());
                Map<String, Object> x = new LinkedHashMap<>();
                x.put("userId", om.getUserId());
                x.put("name", om.getName());
                x.put("departmentId", om.getDepartmentId());
                x.put("institutionId", om.getInstitutionId());
                x.put("jobTitle", om.getJobTitle());
                x.put("employeeNo", om.getEmployeeNo());
                x.put("giteeUsername", acc.getGiteeUsername());
                x.put("giteeName", acc.getGiteeName());
                x.put("alreadyMember", exist != null);
                x.put("memberId", exist == null ? null : exist.getId());
                x.put("role", exist == null ? null : exist.getRole());
                out.add(x);
            }
        }
        return out;
    }

    private static boolean matches(String kw, String... fields) {
        for (String f : fields) {
            if (f != null && f.toLowerCase(Locale.ROOT).contains(kw)) {
                return true;
            }
        }
        return false;
    }

    // ======================================================================
    // 定时校准（处理「用户直接在 Gitee 网页操作」导致的不一致）
    // ======================================================================

    /**
     * 校准单个项目的成员：把**本地待同步**的成员补推，并回报 Gitee 侧的外部变更。
     *
     * <p>处理两类不一致：</p>
     * <ol>
     *   <li>本地 PENDING（成员刚绑定 Gitee）→ 补推为协作者；</li>
     *   <li>Gitee 侧出现本地没有的协作者 → 记为 {@code source=GITEE} 落库，
     *       让管理员在平台上看得到（而不是「Gitee 上有、平台上没有」的黑洞）。</li>
     * </ol>
     */
    public void calibrate(GiteeProject p) {
        if (!StringUtils.hasText(p.getGiteeRepo())) {
            return;
        }
        // ① 补推本地待同步成员
        List<GiteeRepoMember> pending = memberMapper.selectList(new LambdaQueryWrapper<GiteeRepoMember>()
                .eq(GiteeRepoMember::getProjectId, p.getId())
                .ne(GiteeRepoMember::getSyncStatus, GiteeRepoMember.SYNC_SYNCED));
        for (GiteeRepoMember m : pending) {
            if (m.getUserId() != null && !StringUtils.hasText(m.getGiteeUsername())) {
                GiteeAccount acc = tokenService.findAccount(p.getTenantId(), m.getUserId());
                if (acc != null) {
                    GiteeRepoMember upd = new GiteeRepoMember();
                    upd.setId(m.getId());
                    upd.setGiteeUsername(acc.getGiteeUsername());
                    upd.setGiteeUid(acc.getGiteeUid());
                    upd.setUpdatedAt(LocalDateTime.now());
                    memberMapper.updateById(upd);
                }
            }
            enqueueSync(p, m.getId());
        }

        // ② 发现 Gitee 侧的外部协作者
        List<Map<String, Object>> remote;
        try {
            remote = giteeCollaborators(p);
        } catch (Exception e) {
            log.warn("校准项目 {} 成员失败（读取 Gitee 协作者）：{}", p.getId(), e.getMessage());
            return;
        }
        for (Map<String, Object> who : remote) {
            String login = trim(who.get("login"));
            if (!StringUtils.hasText(login)) {
                continue;
            }
            Long n = memberMapper.selectCount(new LambdaQueryWrapper<GiteeRepoMember>()
                    .eq(GiteeRepoMember::getProjectId, p.getId())
                    .eq(GiteeRepoMember::getGiteeUsername, login));
            if (n != null && n > 0) {
                continue;
            }
            GiteeRepoMember m = new GiteeRepoMember();
            m.setTenantId(p.getTenantId());
            m.setProjectId(p.getId());
            m.setGiteeUsername(login);
            m.setGiteeUid(asLong(who.get("id")));
            m.setRole(GiteeRepoMember.ROLE_WRITE);
            m.setSource(GiteeRepoMember.SOURCE_GITEE);
            m.setSyncStatus(GiteeRepoMember.SYNC_SYNCED);
            m.setSyncedAt(LocalDateTime.now());
            m.setCreatedAt(LocalDateTime.now());
            try {
                memberMapper.insert(m);
                log.info("校准发现 Gitee 侧新增协作者 project={} login={}", p.getId(), login);
            } catch (Exception e) {
                // 唯一键冲突 = 并发下已被其他线程写入，忽略
                log.debug("协作者 {} 已存在，跳过", login);
            }
        }
    }

    /** 读取 Gitee 协作者（独立方法便于单测替换）。 */
    List<Map<String, Object>> giteeCollaborators(GiteeProject p) {
        String token = tokenService.requireAccessTokenForProject(p);
        return client.listCollaborators(token, p.getGiteeOwner(), p.getGiteeRepo());
    }

    private GiteeAccount findByUsername(Long tenantId, String username) {
        List<GiteeAccount> list = tokenService.allAccounts(tenantId);
        return list.stream().filter(a -> username.equalsIgnoreCase(a.getGiteeUsername())).findFirst().orElse(null);
    }

    private void enqueueSync(GiteeProject p, Long memberId) {
        enqueueSync(p, memberId, GiteeMemberTaskHandler.OP_ADD);
    }

    private void enqueueSync(GiteeProject p, Long memberId, String op) {
        taskService.enqueue(p.getTenantId(), GiteeTask.TYPE_SYNC_MEMBER, "MEMBER", memberId,
                Map.of("op", op, "projectId", p.getId()));
    }

    /** 角色规范化：只接受 READ / WRITE / ADMIN。 */
    static String normalizeRole(Object v) {
        String s = v == null ? "" : String.valueOf(v).trim().toUpperCase(Locale.ROOT);
        return switch (s) {
            case "READ", "PULL" -> GiteeRepoMember.ROLE_READ;
            case "ADMIN", "MAINTAIN" -> GiteeRepoMember.ROLE_ADMIN;
            default -> GiteeRepoMember.ROLE_WRITE;
        };
    }

    private static String trim(Object o) {
        return o == null ? null : String.valueOf(o).trim();
    }

    private static Long asLong(Object o) {
        if (o == null) {
            return null;
        }
        try {
            return Long.parseLong(String.valueOf(o).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** 判断成员是否为项目创建者（拆成独立类是为了让语义显式，而不是散落一个 equals）。 */
    static final class PermissionCatalogCreatorGuard {
        static boolean isCreator(GiteeProject p, GiteeRepoMember m) {
            return p.getCreatedBy() != null && p.getCreatedBy().equals(m.getUserId());
        }

        private PermissionCatalogCreatorGuard() {
        }
    }
}
