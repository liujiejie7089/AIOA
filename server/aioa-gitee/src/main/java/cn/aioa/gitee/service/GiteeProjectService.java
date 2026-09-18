package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.client.RepoProviderClient;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.entity.GiteeRepoMember;
import cn.aioa.gitee.entity.GiteeTask;
import cn.aioa.gitee.entity.GiteeTeam;
import cn.aioa.gitee.mapper.GiteeProjectMapper;
import cn.aioa.gitee.mapper.GiteeRepoMemberMapper;
import cn.aioa.gitee.mapper.GiteeTeamMapper;
import cn.aioa.gitee.support.GiteeNaming;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
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
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 平台项目 ↔ Gitee 仓库：创建、查询、软删。
 *
 * <p><b>部门隔离的口径</b>（越界一律 404，不泄露存在性，与全站一致）：</p>
 * <table>
 *   <tr><th>角色</th><th>可见范围</th></tr>
 *   <tr><td>平台管理员</td><td>跨租户**只读**</td></tr>
 *   <tr><td>租户管理员</td><td>本租户全部部门</td></tr>
 *   <tr><td>企业管理员</td><td>本机构下的部门</td></tr>
 *   <tr><td>部门负责人</td><td>其负责的部门</td></tr>
 *   <tr><td>机构成员</td><td>本部门项目 + 被显式加为仓库成员的项目</td></tr>
 * </table>
 *
 * <p><b>建项目为什么先要求绑定 Gitee</b>：建仓是以**创建者身份**调用 Gitee 的
 * （仓库归属他的组织/命名空间权限）。若不前置校验，项目会先落库再在异步任务里失败，
 * 用户看到的是一个永远「创建中」的空项目 —— 不如在入口就说清楚。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeProjectService {

    private final GiteeProjectMapper projectMapper;
    private final GiteeTeamMapper teamMapper;
    private final GiteeRepoMemberMapper memberMapper;
    private final OrgDepartmentMapper departmentMapper;
    private final OrgGuard guard;
    private final GiteeTokenService tokenService;
    private final GiteeTaskService taskService;
    private final RepoProviderSettings props;
    private final RepoProviderClient client;
    private final GiteeTenantConfigService tenantConfigService;

    // ======================================================================
    // 创建
    // ======================================================================

    /**
     * 新建项目并在 Gitee 建仓。
     *
     * <p>本方法只做「校验 + 落库 + 入队」：真正的建仓在异步任务里执行。
     * 因此接口是毫秒级返回，用户看到的是「创建中」而不是转圈等待外网调用。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public GiteeProject create(AuthUser user, Map<String, Object> body) {
        tokenService.assertEnabled();
        requirePermission(user, PermissionCatalog.PROJECT_MANAGE);

        Long tenantId = guard.tenantId();
        // 租户级开关：该租户被显式关闭 Gitee 联动时，不允许新建项目
        if (!tenantConfigService.tenantEnabled(tenantId)) {
            throw BizException.badRequest("本企业已关闭 " + props.providerLabel() + " 仓库联动，无法新建项目；如需使用请联系租户管理员开启");
        }
        String name = str(body.get("name"));
        if (!StringUtils.hasText(name)) {
            throw BizException.badRequest("项目名称不能为空");
        }
        Long departmentId = asLong(body.get("departmentId"));
        if (departmentId == null) {
            throw BizException.badRequest("请选择项目归属部门");
        }
        OrgDepartment dept = requireDepartment(tenantId, departmentId);
        assertCanCreateIn(user, dept);

        // 建仓需要创建者的 Gitee 授权：前置校验，避免落库后才在异步任务里失败
        String token = tokenService.requireAccessToken(tenantId, user.getUserId());
        if (token == null || token.isBlank()) {
            throw BizException.badRequest(props.providerLabel() + " 授权无效，请重新绑定后重试");
        }

        GiteeTeam team = resolveTeam(tenantId, dept);
        String repoPath = GiteeNaming.repoPath(name, props.getRepoNameMaxLength(), team.getNamespace());
        assertRepoPathFree(tenantId, repoPath);

        GiteeProject p = new GiteeProject();
        p.setTenantId(tenantId);
        p.setDepartmentId(departmentId);
        p.setTeamId(team.getId());
        p.setName(name);
        p.setRepoName(repoPath);
        p.setDescription(str(body.get("description")));
        p.setVisibility(parseVisibility(body.get("visibility")));
        // 仓库 owner 由「每租户组织解析器」决定：解析为空说明本企业既没配组织、全局也没配 → 明确拒绝，
        // 而不是悄悄建一个没有归属组织的空项目。
        String owner = tenantConfigService.effectiveOrg(tenantId);
        if (!StringUtils.hasText(owner)) {
            throw BizException.badRequest("本企业未配置 " + props.providerLabel() + " 组织，请先在「项目与仓库」中配置");
        }
        p.setGiteeOwner(owner);
        p.setGiteeRepo(repoPath);
        // 默认分支取**托管平台的**默认值（Gitee=master、Gitea=main）。
        // 此前硬编码 "master"，切到 Gitea 后写文件/读目录/文件链接会全部 404。
        // 这只是建仓前的占位值：建仓任务会用接口返回的 default_branch 覆盖它。
        p.setDefaultBranch(client.defaultBranch());
        p.setStatus(GiteeProject.STATUS_CREATING);
        p.setPurgeRepo(Boolean.TRUE.equals(body.get("purgeRepo")));
        p.setCreatedBy(user.getUserId());
        p.setCreatedAt(LocalDateTime.now());
        projectMapper.insert(p);

        // 创建者自动成为仓库管理员（否则他建的仓库自己都没权限，说不通）
        taskService.enqueue(tenantId, GiteeTask.TYPE_CREATE_REPO, "PROJECT", p.getId(), Map.of());
        log.info("项目已创建（待建仓）id={} name={} dept={} repo={}", p.getId(), name, departmentId, repoPath);
        return p;
    }

    /** 建仓失败后重试。 */
    public GiteeProject retry(AuthUser user, Long projectId) {
        GiteeProject p = requireVisible(user, projectId, true);
        if (GiteeProject.STATUS_ACTIVE.equals(p.getStatus())) {
            throw BizException.badRequest("项目已就绪，无需重试");
        }
        GiteeProject upd = new GiteeProject();
        upd.setId(p.getId());
        upd.setStatus(GiteeProject.STATUS_CREATING);
        upd.setErrorMsg(null);
        upd.setUpdatedAt(LocalDateTime.now());
        projectMapper.updateById(upd);
        taskService.enqueue(p.getTenantId(), GiteeTask.TYPE_CREATE_REPO, "PROJECT", p.getId(), Map.of());
        return projectMapper.selectById(p.getId());
    }

    // ======================================================================
    // 查询
    // ======================================================================

    /** 项目列表（按可见范围过滤）。 */
    public List<GiteeProject> list(AuthUser user, Long departmentId, String keyword) {
        requirePermission(user, PermissionCatalog.PROJECT_VIEW);
        Long tenantId = guard.tenantId();
        LambdaQueryWrapper<GiteeProject> q = new LambdaQueryWrapper<GiteeProject>()
                .eq(GiteeProject::getTenantId, tenantId)
                .orderByDesc(GiteeProject::getId);
        if (departmentId != null) {
            q.eq(GiteeProject::getDepartmentId, departmentId);
        }
        if (StringUtils.hasText(keyword)) {
            q.and(w -> w.like(GiteeProject::getName, keyword).or().like(GiteeProject::getRepoName, keyword));
        }
        List<GiteeProject> all = projectMapper.selectList(q);
        // 平台管理员跨租户只读：其 tenantId 为 0，这里放开为「按入参租户」，其余按作用域过滤
        if (PermissionCatalog.isPlatformAdmin(user)) {
            return all;
        }
        Set<Long> visibleDepts = visibleDepartmentIds(user, tenantId);
        Set<Long> memberProjectIds = memberProjectIds(tenantId, user.getUserId());
        return all.stream()
                .filter(p -> visibleDepts.contains(p.getDepartmentId()) || memberProjectIds.contains(p.getId()))
                .collect(Collectors.toList());
    }

    /** 项目详情（含成员、Gitee 地址、Webhook 状态）。 */
    public Map<String, Object> detail(AuthUser user, Long projectId) {
        GiteeProject p = requireVisible(user, projectId, false);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("project", toView(p));
        out.put("repository", repoView(p));
        out.put("webhook", webhookView(p));
        out.put("members", listMembers(user, projectId));
        out.put("canManage", canManage(user, p));
        return out;
    }

    /** 对外视图：**绝不包含** webhook_secret 与任何令牌字段。 */
    public Map<String, Object> toView(GiteeProject p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("departmentId", p.getDepartmentId());
        m.put("teamId", p.getTeamId());
        m.put("name", p.getName());
        m.put("repoName", p.getRepoName());
        m.put("description", p.getDescription());
        m.put("visibility", p.getVisibility());
        m.put("status", p.getStatus());
        m.put("errorMsg", p.getErrorMsg());
        m.put("purgeRepo", p.getPurgeRepo());
        m.put("giteeOwner", p.getGiteeOwner());
        m.put("giteeRepo", p.getGiteeRepo());
        m.put("defaultBranch", p.getDefaultBranch());
        m.put("htmlUrl", p.getGiteeHtmlUrl());
        m.put("sshUrl", p.getGiteeSshUrl());
        m.put("httpsUrl", p.getGiteeHttpsUrl());
        m.put("createdBy", p.getCreatedBy());
        m.put("createdAt", p.getCreatedAt());
        return m;
    }

    private Map<String, Object> repoView(GiteeProject p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("owner", p.getGiteeOwner());
        m.put("repo", p.getGiteeRepo());
        m.put("htmlUrl", p.getGiteeHtmlUrl());
        m.put("sshUrl", p.getGiteeSshUrl());
        m.put("httpsUrl", p.getGiteeHttpsUrl());
        m.put("defaultBranch", p.getDefaultBranch());
        // 本地 push 的完整命令：把「怎么用」直接给到开发者，而不是只丢一个地址
        if (p.getGiteeSshUrl() != null) {
            m.put("cloneCommand", "git clone " + p.getGiteeSshUrl());
        }
        return m;
    }

    private Map<String, Object> webhookView(GiteeProject p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("configured", p.getWebhookId() != null);
        m.put("hookId", p.getWebhookId());
        m.put("events", p.getWebhookEvents());
        // 只回「是否已配置」，不回密钥本身
        m.put("secretConfigured", StringUtils.hasText(p.getWebhookSecret()));
        return m;
    }

    // ======================================================================
    // 软删
    // ======================================================================

    /**
     * 软删项目。
     *
     * @param purgeRepo 是否同时删除 Gitee 仓库。**默认不删**：代码一旦删除不可恢复，
     *                  而平台侧的「移除项目」多半只是整理目录。需要真删必须由调用方显式传入。
     */
    @Transactional(rollbackFor = Exception.class)
    public void softDelete(AuthUser user, Long projectId, boolean purgeRepo) {
        GiteeProject p = requireVisible(user, projectId, true);
        // 先撤掉未执行的任务：否则「删项目」之后建仓任务还会把仓库建出来
        taskService.cancelPending("PROJECT", projectId);

        GiteeProject upd = new GiteeProject();
        upd.setId(p.getId());
        upd.setStatus(GiteeProject.STATUS_DELETED);
        upd.setPurgeRepo(purgeRepo);
        upd.setUpdatedAt(LocalDateTime.now());
        projectMapper.updateById(upd);
        // 软删（MyBatis-Plus 逻辑删除：@TableLogic 字段置 now()）
        projectMapper.deleteById(p.getId());

        if (purgeRepo && StringUtils.hasText(p.getGiteeRepo())) {
            // 仓库信息必须**随任务入队**，不能在执行时回读项目行：
            // 项目行上面已被逻辑删除（@TableLogic 置 deleted_at），执行侧 selectById 会拿到
            // null —— 旧实现正是在这里静默 return，导致 purgeRepo=true 变成「什么都不做却报成功」。
            // deleteWebhook 早就按这个约定传了 payload，deleteRepo 先前漏了，现补齐。
            taskService.enqueue(p.getTenantId(), GiteeTask.TYPE_DELETE_REPO, "PROJECT", p.getId(),
                    Map.of("owner", p.getGiteeOwner() == null ? "" : p.getGiteeOwner(),
                            "repo", p.getGiteeRepo(),
                            "createdBy", p.getCreatedBy() == null ? 0L : p.getCreatedBy()));
        } else if (p.getWebhookId() != null) {
            // 保留仓库时，必须**摘掉平台自己挂的 Webhook**：
            // 那个钩子指向 /gitee/webhook/{projectId}，项目已删，继续投递只会一直得到
            // PROJECT_NOT_FOUND；而且若之后有人用同一路径重建项目，仓库上就会挂着
            // 两个钩子（新旧各一个），事件被重复投递。Webhook 是平台自己的管线，
            // 不是用户的代码，所以删项目时应当一并回收。
            taskService.enqueue(p.getTenantId(), GiteeTask.TYPE_DELETE_WEBHOOK, "PROJECT", p.getId(),
                    Map.of("hookId", p.getWebhookId(),
                            "owner", p.getGiteeOwner() == null ? "" : p.getGiteeOwner(),
                            "repo", p.getGiteeRepo() == null ? "" : p.getGiteeRepo(),
                            "createdBy", p.getCreatedBy() == null ? 0L : p.getCreatedBy()));
        }
        log.info("项目已软删 id={} purgeRepo={}", projectId, purgeRepo);
    }

    // ======================================================================
    // 部门与团队
    // ======================================================================

    /** 取（或建立）部门对应的团队记录。 */
    @Transactional(rollbackFor = Exception.class)
    public GiteeTeam resolveTeam(Long tenantId, OrgDepartment dept) {
        GiteeTeam existing = teamMapper.selectOne(new LambdaQueryWrapper<GiteeTeam>()
                .eq(GiteeTeam::getTenantId, tenantId)
                .eq(GiteeTeam::getDepartmentId, dept.getId())
                .last("limit 1"));
        if (existing != null) {
            return existing;
        }
        GiteeTeam t = new GiteeTeam();
        t.setTenantId(tenantId);
        t.setDepartmentId(dept.getId());
        // 部门的组织归属走「每租户组织解析器」（优先本租户配置，回落全局默认）
        t.setOrgName(tenantConfigService.effectiveOrg(tenantId));
        t.setTeamName(dept.getName());
        t.setNamespace(GiteeNaming.namespaceOf(dept.getId()));
        // 开源 gitee.com 无组织级团队 API（实测），故默认走命名空间隔离
        t.setProvider(GiteeTeam.PROVIDER_NAMESPACE);
        t.setProvisioned(false);
        t.setRemark("部门隔离：仓库命名前缀 " + t.getNamespace());
        t.setCreatedAt(LocalDateTime.now());
        teamMapper.insert(t);
        return t;
    }

    /** 部门列表（供建项目时选择，按作用域过滤）。 */
    public List<Map<String, Object>> selectableDepartments(AuthUser user) {
        requirePermission(user, PermissionCatalog.PROJECT_VIEW);
        Long tenantId = guard.tenantId();
        Set<Long> scoped = visibleDepartmentIds(user, tenantId);
        List<OrgDepartment> depts = departmentMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getTenantId, tenantId)
                .eq(OrgDepartment::getStatus, "ACTIVE")
                .orderByAsc(OrgDepartment::getId));
        List<Map<String, Object>> out = new ArrayList<>();
        for (OrgDepartment d : depts) {
            if (!scoped.contains(d.getId())) {
                continue;
            }
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", d.getId());
            m.put("name", d.getName());
            m.put("institutionId", d.getInstitutionId());
            m.put("namespace", GiteeNaming.namespaceOf(d.getId()));
            out.add(m);
        }
        return out;
    }

    /** 当前用户在某租户内可见的部门集合。 */
    public Set<Long> visibleDepartmentIds(AuthUser user, Long tenantId) {
        if (PermissionCatalog.isPlatformAdmin(user)) {
            return departmentMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                            .eq(OrgDepartment::getTenantId, tenantId)).stream()
                    .map(OrgDepartment::getId).collect(Collectors.toSet());
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)) {
            return departmentMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                            .eq(OrgDepartment::getTenantId, tenantId)
                            .eq(OrgDepartment::getStatus, "ACTIVE")).stream()
                    .map(OrgDepartment::getId).collect(Collectors.toSet());
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_ORG_ADMIN)) {
            Long inst = guard.resolveInstitutionId(user.getUserId());
            if (inst == null) {
                return Set.of();
            }
            return departmentMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                            .eq(OrgDepartment::getTenantId, tenantId)
                            .eq(OrgDepartment::getInstitutionId, inst)).stream()
                    .map(OrgDepartment::getId).collect(Collectors.toSet());
        }
        Set<Long> ids = new java.util.HashSet<>();
        // 部门负责人：其负责的部门
        guard.ledDepartments(user.getUserId()).forEach(d -> ids.add(d.getId()));
        // 机构成员：本部门（含其所属部门）
        if (user.getDepartmentId() != null) {
            ids.add(user.getDepartmentId());
        }
        return ids;
    }

    private Set<Long> memberProjectIds(Long tenantId, Long userId) {
        if (userId == null) {
            return Set.of();
        }
        return memberMapper.selectList(new LambdaQueryWrapper<GiteeRepoMember>()
                        .eq(GiteeRepoMember::getTenantId, tenantId)
                        .eq(GiteeRepoMember::getUserId, userId)).stream()
                .map(GiteeRepoMember::getProjectId).collect(Collectors.toSet());
    }

    // ======================================================================
    // 作用域与权限
    // ======================================================================

    /**
     * 取项目并校验可见性。
     *
     * @param forWrite true 时额外要求写权限（创建者 / 机构管理员及以上）
     * @throws BizException 404（越界或不存在，不区分以免泄露存在性）
     */
    public GiteeProject requireVisible(AuthUser user, Long projectId, boolean forWrite) {
        GiteeProject p = projectMapper.selectById(projectId);
        if (p == null) {
            throw BizException.notFound("项目不存在");
        }
        if (PermissionCatalog.isPlatformAdmin(user)) {
            if (forWrite) {
                throw BizException.forbidden("平台管理员为运维只读视角，不能修改租户项目");
            }
            return p;
        }
        if (!Objects.equals(p.getTenantId(), guard.tenantId())) {
            throw BizException.notFound("项目不存在");
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)) {
            return p;
        }
        boolean inScope = visibleDepartmentIds(user, p.getTenantId()).contains(p.getDepartmentId())
                || memberProjectIds(p.getTenantId(), user.getUserId()).contains(p.getId());
        if (!inScope) {
            throw BizException.notFound("项目不存在");
        }
        if (forWrite && !canManage(user, p)) {
            throw BizException.forbidden("仅项目创建者或机构管理员及以上可修改该项目");
        }
        return p;
    }

    /** 是否可管理（改配置 / 加成员 / 删项目）。 */
    public boolean canManage(AuthUser user, GiteeProject p) {
        if (PermissionCatalog.isPlatformAdmin(user)) {
            return false;
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)
                || OrgGuard.hasRole(user, OrgGuard.ROLE_ORG_ADMIN)) {
            return true;
        }
        if (PermissionCatalog.isCreator(user, p.getCreatedBy())) {
            return true;
        }
        // 部门负责人可管理本部门项目
        return guard.ledDepartments(user.getUserId()).stream()
                .anyMatch(d -> Objects.equals(d.getId(), p.getDepartmentId()));
    }

    private void assertCanCreateIn(AuthUser user, OrgDepartment dept) {
        if (PermissionCatalog.isPlatformAdmin(user)) {
            throw BizException.forbidden("平台管理员为运维只读视角，不能在租户下创建项目");
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)) {
            return;
        }
        if (!visibleDepartmentIds(user, dept.getTenantId()).contains(dept.getId())) {
            throw BizException.forbidden("只能在本部门（或本机构管辖范围）内创建项目");
        }
    }

    private OrgDepartment requireDepartment(Long tenantId, Long departmentId) {
        OrgDepartment d = departmentMapper.selectById(departmentId);
        if (d == null || !Objects.equals(d.getTenantId(), tenantId) || d.getDeletedAt() != null) {
            throw BizException.badRequest("归属部门不存在或不属于当前租户");
        }
        return d;
    }

    private void assertRepoPathFree(Long tenantId, String repoPath) {
        Long n = projectMapper.selectCount(new LambdaQueryWrapper<GiteeProject>()
                .eq(GiteeProject::getTenantId, tenantId)
                .eq(GiteeProject::getRepoName, repoPath));
        if (n != null && n > 0) {
            throw BizException.badRequest("同名仓库已存在：" + repoPath + "，请换一个项目名称");
        }
    }

    private void requirePermission(AuthUser user, String permission) {
        if (!PermissionCatalog.holds(user, permission)) {
            throw BizException.forbidden("当前角色无权访问「项目与代码仓库」");
        }
    }

    private List<Map<String, Object>> listMembers(AuthUser user, Long projectId) {
        return memberMapper.selectList(new LambdaQueryWrapper<GiteeRepoMember>()
                        .eq(GiteeRepoMember::getProjectId, projectId)
                        .orderByAsc(GiteeRepoMember::getId)).stream()
                .map(m -> {
                    Map<String, Object> x = new LinkedHashMap<>();
                    x.put("id", m.getId());
                    x.put("userId", m.getUserId());
                    x.put("giteeUsername", m.getGiteeUsername());
                    x.put("role", m.getRole());
                    x.put("source", m.getSource());
                    x.put("syncStatus", m.getSyncStatus());
                    x.put("lastError", m.getLastError());
                    x.put("syncedAt", m.getSyncedAt());
                    return x;
                })
                .collect(Collectors.toList());
    }

    private static String parseVisibility(Object v) {
        String s = v == null ? "" : String.valueOf(v).trim().toLowerCase();
        return GiteeProject.VISIBILITY_PUBLIC.equals(s)
                ? GiteeProject.VISIBILITY_PUBLIC : GiteeProject.VISIBILITY_PRIVATE;
    }

    private static String str(Object o) {
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
}
