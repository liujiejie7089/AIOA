package cn.aioa.project.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.service.GiteeProjectService;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.entity.PmProject;
import cn.aioa.project.entity.PmProjectMember;
import cn.aioa.project.entity.PmTask;
import cn.aioa.project.mapper.PmProjectMapper;
import cn.aioa.project.mapper.PmProjectMemberMapper;
import cn.aioa.project.mapper.PmRepoBindMapper;
import cn.aioa.project.mapper.PmTaskMapper;
import cn.aioa.project.support.PmProjectRoles;
import cn.aioa.project.support.PmProjectStatus;
import cn.aioa.project.support.PmProjectType;
import cn.aioa.project.support.ProjectTypeGuard;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 项目管理（PM）主服务：立项 / 查询 / 改信息 / 改状态 / 软删。
 *
 * <p><b>数据范围口径</b>（沿用 {@code GiteeProjectService} 的约定，越界一律 404 不泄露存在性）：</p>
 * <table>
 *   <tr><th>角色</th><th>可见范围</th></tr>
 *   <tr><td>平台管理员</td><td>跨租户**只读**</td></tr>
 *   <tr><td>租户管理员</td><td>本租户全部</td></tr>
 *   <tr><td>企业管理员</td><td>本机构</td></tr>
 *   <tr><td>部门负责人</td><td>其负责的部门</td></tr>
 *   <tr><td>机构成员</td><td>本部门项目 + 被显式加为项目成员的项目（BR-15「我是成员」）</td></tr>
 * </table>
 *
 * <p><b>类型即配置面（BR-01/02）</b>：所有仓库相关写入都先过 {@link ProjectTypeGuard}，
 * 前端隐藏只是体验，服务端守卫才是边界。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PmProjectService {

    private final PmProjectMapper projectMapper;
    private final PmProjectMemberMapper memberMapper;
    private final PmTaskMapper taskMapper;
    private final PmRepoBindMapper repoBindMapper;
    /** 建项目时自动建「项目文档」根目录（用户关键词：每个项目创建一个文档目录）。 */
    private final cn.aioa.project.mapper.PmFolderMapper pmFolderMapper;
    /** 项目软删时级联软删其文档索引（BR-07/BR-14：只软删索引，不删 sys_file 字节）。 */
    private final cn.aioa.project.mapper.PmDocumentMapper pmDocumentMapper;
    private final OrgMemberMapper orgMemberMapper;
    private final OrgDepartmentMapper departmentMapper;
    private final OrgGuard guard;
    /** 仅用于开发项目的「自动建仓」；建仓失败不阻断立项（见 {@link #create}）。 */
    private final GiteeProjectService giteeProjectService;

    // ======================================================================
    // 新建
    // ======================================================================

    /**
     * 新建项目（业务项目 / 开发项目）。
     *
     * <p>body 关键字段：{@code projectNo} {@code name} {@code projectType}
     * {@code departmentId} {@code ownerMemberId} {@code budgetAmount}
     * {@code startDate} {@code endDate} {@code description}。</p>
     *
     * <p>开发项目额外支持：</p>
     * <ul>
     *   <li>{@code bindRepoId}：绑定一个**既有**仓库（必须尚未归属任何项目，BR-06）；</li>
     *   <li>{@code createRepo=true} + {@code repoVisibility}：走既有 Gitee 建仓链路（异步），
     *       建仓失败**不阻断立项**，失败原因随响应 {@code repoWarning} 返回（不静默成功）；</li>
     *   <li>两者都不给 = 暂不绑定（可后补）。</li>
     * </ul>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> create(AuthUser user, Map<String, Object> body) {
        requirePermission(user, PermissionCatalog.PM_PROJECT_CREATE);
        Long tenantId = guard.tenantId();

        String projectNo = str(body.get("projectNo"));
        if (!StringUtils.hasText(projectNo)) {
            throw BizException.badRequest("项目编号不能为空");
        }
        String name = str(body.get("name"));
        if (!StringUtils.hasText(name)) {
            throw BizException.badRequest("项目名称不能为空");
        }
        String projectType = str(body.get("projectType"));
        if (!PmProjectType.isValid(projectType)) {
            throw BizException.badRequest("项目类型必须为 BUSINESS（业务项目）或 DEV（开发项目）");
        }

        Long bindRepoId = asLong(body.get("bindRepoId"));
        boolean createRepo = Boolean.TRUE.equals(body.get("createRepo"));

        // BR-01：业务项目不得携带任何仓库配置（前端隐藏 + 后端拒绝，双向）
        ProjectTypeGuard.assertRepoAllowed(projectType, bindRepoId != null || createRepo);

        // 编号唯一：与唯一键 uk_pm_project_no（含 alive）同口径 —— 只查存活行，
        // 软删释放编号（旧行已退出运营面，重号不会造成「两条同名项目」）。
        Long dup = projectMapper.selectCount(new LambdaQueryWrapper<PmProject>()
                .eq(PmProject::getTenantId, tenantId)
                .eq(PmProject::getProjectNo, projectNo));
        if (dup != null && dup > 0) {
            throw new BizException(409, "项目编号已存在：" + projectNo);
        }

        Long departmentId = asLong(body.get("departmentId"));
        if (departmentId == null) {
            departmentId = 0L;
        }
        Long institutionId = resolveInstitutionForCreate(user, tenantId, departmentId);

        Long ownerMemberId = asLong(body.get("ownerMemberId"));
        if (ownerMemberId != null) {
            requireActiveMember(tenantId, ownerMemberId);
        }

        PmProject p = new PmProject();
        p.setTenantId(tenantId);
        p.setProjectNo(projectNo);
        p.setName(name);
        p.setProjectType(projectType);
        // 直接生效：立项无需审批（如需审批可配置，见 docs/40 BR-11 的后续批次）
        p.setStatus(PmProjectStatus.ACTIVE);
        p.setInstitutionId(institutionId);
        p.setDepartmentId(departmentId);
        p.setOwnerMemberId(ownerMemberId);
        p.setBudgetAmount(decimal(body.get("budgetAmount")));
        p.setStartDate(date(body.get("startDate")));
        p.setEndDate(date(body.get("endDate")));
        p.setDescription(str(body.get("description")));
        p.setCreatedBy(user.getUserId());
        p.setCreatedAt(LocalDateTime.now());
        projectMapper.insert(p);

        // 负责人自动成为项目成员（角色 OWNER）—— 否则会出现「有负责人但不是成员」的悬空态
        if (ownerMemberId != null) {
            insertMember(p, ownerMemberId, PmProjectRoles.OWNER, user.getUserId());
        }

        // 每个项目自动建「项目文档」根目录（用户关键词：每个项目创建一个文档目录）。
        // 直接写 mapper 而不调 PmDocService：后者依赖本服务（requireVisible），互相注入会成环。
        createProjectRootFolder(p, user.getUserId());

        // 仓库绑定：绑定失败要回滚整个立项（用户明确要求绑，绑不上就不该落库）
        String repoWarning = null;
        if (bindRepoId != null) {
            bindRepo(user, p, bindRepoId);
        } else if (createRepo) {
            // 自动建仓是「尽力而为」：Gitee 未配置组织 / 未绑令牌 / 部门非法时，
            // 建仓不可用，但立项本身仍应成功 —— 把原因作为警告回传，而不是让用户丢一次立项。
            if (departmentId == null || departmentId <= 0) {
                // departmentId=0 是**内部哨兵值**（表示机构直属、未挂具体部门），不是真实部门。
                // 建仓必须落在真实部门下（仓库名派生自部门，`GiteeProjectService.create` 会
                // requireDepartment 校验）。把这个哨兵值原样传下去，只会换来一句
                // 「归属部门不存在或不属于当前租户」，还白跑一次跨模块校验 ——
                // 于是一句话前置拦掉，并给出**可执行**的补救路径。
                repoWarning = "项目已创建，但未自动建仓：自动建仓需要项目先指定归属部门"
                        + "（本项目为机构直属、未挂具体部门，无法派生仓库名）。"
                        + "请编辑项目补上归属部门后重试，或到「仓库总览与配置」建好仓库后"
                        + "回本项目详情页「仓库」页签绑定。";
            } else {
                try {
                    Map<String, Object> cb = new HashMap<>();
                    cb.put("name", name);
                    cb.put("description", str(body.get("description")));
                    cb.put("departmentId", departmentId);
                    cb.put("visibility", str(body.get("repoVisibility")));
                    GiteeProject repo = giteeProjectService.create(user, cb);
                    repoBindMapper.bind(tenantId, repo.getId(), p.getId());
                } catch (Exception e) {
                    repoWarning = "项目已创建，但自动建仓未成功：" + e.getMessage()
                            + "（可先到「仓库总览与配置」建好仓库，再回本项目详情页「代码仓库」页签绑定）";
                    log.warn("自动建仓失败 projectId={} name={}: {}", p.getId(), name, e.toString());
                }
            }
        }

        Map<String, Object> out = detailOf(user, p.getId());
        if (repoWarning != null) {
            out.put("repoWarning", repoWarning);
        }
        log.info("PM 项目已创建 id={} no={} type={} dept={}", p.getId(), projectNo, projectType, departmentId);
        return out;
    }

    // ======================================================================
    // 查询
    // ======================================================================

    /** 项目列表（含筛选：关键字 / 类型 / 状态 / 部门）。 */
    public List<Map<String, Object>> list(AuthUser user, String keyword, String projectType,
                                          String status, Long departmentId) {
        requirePermission(user, PermissionCatalog.PM_PROJECT_VIEW);
        Long tenantId = guard.tenantId();

        LambdaQueryWrapper<PmProject> q = new LambdaQueryWrapper<PmProject>()
                .eq(PmProject::getTenantId, tenantId)
                .eq(StringUtils.hasText(projectType), PmProject::getProjectType, projectType)
                .eq(StringUtils.hasText(status), PmProject::getStatus, status)
                .eq(departmentId != null, PmProject::getDepartmentId, departmentId)
                .and(StringUtils.hasText(keyword), w -> w
                        .like(PmProject::getName, keyword).or().like(PmProject::getProjectNo, keyword))
                .orderByDesc(PmProject::getId);

        List<PmProject> all = projectMapper.selectList(q);
        List<PmProject> visible = new ArrayList<>();
        for (PmProject p : all) {
            if (canSee(user, p)) {
                visible.add(p);
            }
        }

        Map<Long, long[]> taskStats = taskStats(visible.stream().map(PmProject::getId).toList());
        Map<Long, Long> memberCounts = memberCounts(visible.stream().map(PmProject::getId).toList());
        List<Map<String, Object>> out = new ArrayList<>();
        for (PmProject p : visible) {
            out.add(toView(user, p, taskStats.get(p.getId()), memberCounts.getOrDefault(p.getId(), 0L)));
        }
        return out;
    }

    /** 项目详情（含统计与我的项目角色）。 */
    public Map<String, Object> detail(AuthUser user, Long projectId) {
        requireVisible(user, projectId, false);
        return detailOf(user, projectId);
    }

    private Map<String, Object> detailOf(AuthUser user, Long projectId) {
        PmProject p = projectMapper.selectById(projectId);
        if (p == null) {
            throw BizException.notFound("项目不存在");
        }
        Map<Long, long[]> st = taskStats(List.of(projectId));
        Map<Long, Long> mc = memberCounts(List.of(projectId));
        Map<String, Object> v = toView(user, p, st.get(projectId), mc.getOrDefault(projectId, 0L));
        v.put("boundRepos", repoBindMapper.listByProject(p.getTenantId(), projectId));
        return v;
    }

    private Map<String, Object> toView(AuthUser user, PmProject p, long[] taskStat, long memberCount) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("projectNo", p.getProjectNo());
        m.put("name", p.getName());
        m.put("projectType", p.getProjectType());
        m.put("status", p.getStatus());
        m.put("institutionId", p.getInstitutionId());
        m.put("departmentId", p.getDepartmentId());
        m.put("ownerMemberId", p.getOwnerMemberId());
        m.put("ownerName", ownerName(p.getTenantId(), p.getOwnerMemberId()));
        m.put("budgetAmount", p.getBudgetAmount());
        m.put("startDate", p.getStartDate());
        m.put("endDate", p.getEndDate());
        m.put("description", p.getDescription());
        m.put("createdAt", p.getCreatedAt());
        long taskCount = taskStat == null ? 0 : taskStat[0];
        long doneCount = taskStat == null ? 0 : taskStat[1];
        m.put("taskCount", taskCount);
        m.put("taskDoneCount", doneCount);
        m.put("memberCount", memberCount);
        m.put("repoCount", repoBindMapper.countBound(p.getTenantId(), p.getId()));
        // 我的项目角色：前端据此决定「改信息 / 管成员 / 管任务」按钮是否可点
        PmProjectMember mine = myMembership(p.getTenantId(), p.getId(), user.getUserId());
        m.put("myRole", mine == null ? null : mine.getRoleCode());
        m.put("canManage", canManage(user, p));
        return m;
    }

    // ======================================================================
    // 改信息 / 改状态 / 软删
    // ======================================================================

    /** 改基础信息（含 BR-02 的类型变更守卫）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> update(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = requireVisible(user, projectId, true);

        // BR-02：类型变更
        String newType = str(body.get("projectType"));
        if (StringUtils.hasText(newType) && !newType.equals(p.getProjectType())) {
            ProjectTypeGuard.assertTypeChangeable(p.getProjectType(), newType,
                    repoBindMapper.countBound(p.getTenantId(), p.getId()),
                    repoBindMapper.countTasksWithRepo(p.getTenantId(), p.getId()));
            p.setProjectType(newType);
        }

        if (body.containsKey("name")) {
            String name = str(body.get("name"));
            if (!StringUtils.hasText(name)) {
                throw BizException.badRequest("项目名称不能为空");
            }
            p.setName(name);
        }
        if (body.containsKey("description")) {
            p.setDescription(str(body.get("description")));
        }
        if (body.containsKey("budgetAmount")) {
            p.setBudgetAmount(decimal(body.get("budgetAmount")));
        }
        if (body.containsKey("startDate")) {
            p.setStartDate(date(body.get("startDate")));
        }
        if (body.containsKey("endDate")) {
            p.setEndDate(date(body.get("endDate")));
        }
        if (body.containsKey("departmentId")) {
            Long dept = asLong(body.get("departmentId"));
            if (dept != null && !Objects.equals(dept, p.getDepartmentId())) {
                p.setInstitutionId(resolveInstitutionForCreate(user, p.getTenantId(), dept));
                p.setDepartmentId(dept);
            }
        }
        if (body.containsKey("ownerMemberId")) {
            Long owner = asLong(body.get("ownerMemberId"));
            if (owner != null) {
                requireActiveMember(p.getTenantId(), owner);
            }
            p.setOwnerMemberId(owner);
        }
        p.setUpdatedAt(LocalDateTime.now());
        projectMapper.updateById(p);
        return detailOf(user, projectId);
    }

    /** 改状态（走 {@link PmProjectStatus#canTransition} 白名单）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> changeStatus(AuthUser user, Long projectId, String status) {
        PmProject p = requireVisible(user, projectId, true);
        if (!PmProjectStatus.isValid(status)) {
            throw BizException.badRequest("未知项目状态：" + status);
        }
        if (!PmProjectStatus.canTransition(p.getStatus(), status)) {
            throw BizException.badRequest("不允许从 " + p.getStatus() + " 变更为 " + status);
        }
        p.setStatus(status);
        p.setUpdatedAt(LocalDateTime.now());
        projectMapper.updateById(p);
        return detailOf(user, projectId);
    }

    /**
     * 软删项目（BR-14 级联）。
     *
     * <p>级联软删：成员、任务（批次 3/4 的文件夹/合同等到时并入同一事务）。
     * **不删** {@code gitee_project}（仓库是外部资产，删项目不等于删代码）与文件字节。
     * 单事务：任一级联失败整体回滚，项目不进入已删态（每一步失败都有终态）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public void softDelete(AuthUser user, Long projectId) {
        PmProject p = requireVisible(user, projectId, true);
        Long tenantId = p.getTenantId();
        memberMapper.delete(new LambdaQueryWrapper<PmProjectMember>()
                .eq(PmProjectMember::getTenantId, tenantId).eq(PmProjectMember::getProjectId, projectId));
        taskMapper.delete(new LambdaQueryWrapper<PmTask>()
                .eq(PmTask::getTenantId, tenantId).eq(PmTask::getProjectId, projectId));
        // 级联软删文档索引与「项目专属」文件夹（BR-07/BR-14）。
        // 只动 scope=PROJECT 的本项目文件夹，**不动** scope=ENTERPRISE（企业级公共文件夹跨项目共享）；
        // 文档只软删索引，**不删** sys_file 字节（保留可追溯）。
        pmDocumentMapper.delete(new LambdaQueryWrapper<cn.aioa.project.entity.PmDocument>()
                .eq(cn.aioa.project.entity.PmDocument::getTenantId, tenantId)
                .eq(cn.aioa.project.entity.PmDocument::getProjectId, projectId));
        pmFolderMapper.delete(new LambdaQueryWrapper<cn.aioa.project.entity.PmFolder>()
                .eq(cn.aioa.project.entity.PmFolder::getTenantId, tenantId)
                .eq(cn.aioa.project.entity.PmFolder::getScope, cn.aioa.project.entity.PmFolder.SCOPE_PROJECT)
                .eq(cn.aioa.project.entity.PmFolder::getProjectId, projectId));
        // 解绑仓库（只置空 pm_project_id，不动 gitee_project 行本身）
        for (Map<String, Object> repo : repoBindMapper.listByProject(tenantId, projectId)) {
            Object rid = repo.get("id");
            if (rid instanceof Number n) {
                repoBindMapper.unbind(tenantId, n.longValue(), projectId);
            }
        }
        projectMapper.deleteById(projectId);
        log.info("PM 项目已软删 id={}（级联：成员 + 任务 + 文档索引 + 项目专属文件夹 + 仓库解绑）", projectId);
    }

    // ======================================================================
    // 仓库绑定（BR-06）
    // ======================================================================

    /** 绑定既有仓库到项目（仅开发项目）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> bindRepo(AuthUser user, Long projectId, Long repoId) {
        PmProject p = requireVisible(user, projectId, true);
        return bindRepo(user, p, repoId);
    }

    private Map<String, Object> bindRepo(AuthUser user, PmProject p, Long repoId) {
        ProjectTypeGuard.assertRepoAllowed(p.getProjectType(), true);
        Map<String, Object> repo = repoBindMapper.findRepo(p.getTenantId(), repoId);
        if (repo == null) {
            throw BizException.badRequest("仓库不存在或不属于当前企业");
        }
        Object already = repo.get("pm_project_id");
        if (already != null && !Objects.equals(asLong(already), p.getId())) {
            throw new BizException(409, "该仓库已归属其它项目，请先在其项目中解绑");
        }
        int n = repoBindMapper.bind(p.getTenantId(), repoId, p.getId());
        if (n == 0 && !Objects.equals(asLong(already), p.getId())) {
            // 影响行数 0 且不是「已绑在本项目」 ⇒ 并发下被别人抢走（BR-06 原子保证）
            throw new BizException(409, "该仓库刚被其它项目绑定，请刷新后重试");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("repoId", repoId);
        out.put("boundRepos", repoBindMapper.listByProject(p.getTenantId(), p.getId()));
        return out;
    }

    /** 解绑（只置空，不删仓库记录，BR-06）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> unbindRepo(AuthUser user, Long projectId, Long repoId) {
        PmProject p = requireVisible(user, projectId, true);
        repoBindMapper.unbind(p.getTenantId(), repoId, p.getId());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("repoId", repoId);
        out.put("boundRepos", repoBindMapper.listByProject(p.getTenantId(), p.getId()));
        return out;
    }

    /** 可绑定的仓库候选（本租户内未归属任何项目的 ACTIVE 仓库）。 */
    public List<Map<String, Object>> bindableRepos(AuthUser user, Long projectId) {
        PmProject p = requireVisible(user, projectId, false);
        if (!PmProjectType.isDev(p.getProjectType())) {
            throw BizException.badRequest("业务项目不支持代码仓库配置");
        }
        return repoBindMapper.listBindable(p.getTenantId());
    }

    /** 项目已绑定的仓库列表。 */
    public List<Map<String, Object>> boundRepos(AuthUser user, Long projectId) {
        PmProject p = requireVisible(user, projectId, false);
        return repoBindMapper.listByProject(p.getTenantId(), projectId);
    }

    /**
     * 可绑定仓库候选（**新建流程专用**：此时还没有项目 id，无从按项目鉴权）。
     *
     * <p>鉴权改用「有没有新建项目的权限」——只有能立项的人才需要挑仓库。
     * 与 {@link #bindableRepos} 同一份查询，两个入口的区别只在鉴权依据。</p>
     */
    public List<Map<String, Object>> bindableReposForCreate(AuthUser user) {
        requirePermission(user, PermissionCatalog.PM_PROJECT_CREATE);
        return repoBindMapper.listBindable(guard.tenantId());
    }

    // ======================================================================
    // 作用域与权限
    // ======================================================================

    /** 取项目并校验可见性；{@code forWrite=true} 时额外要求可管理。 */
    public PmProject requireVisible(AuthUser user, Long projectId, boolean forWrite) {
        PmProject p = projectMapper.selectById(projectId);
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
        if (!canSee(user, p)) {
            throw BizException.notFound("项目不存在");
        }
        if (forWrite && !canManage(user, p)) {
            throw BizException.forbidden("仅项目负责人/项目经理或机构管理员及以上可修改该项目");
        }
        return p;
    }

    /**
     * 可见性判定（**唯一判定点**，list 与 requireVisible 共用）。
     *
     * <p>口径：</p>
     * <ul>
     *   <li>平台管理员：跨租户只读（可见性由调用方在 {@link #requireVisible} 单独放行）；</li>
     *   <li>租户管理员：本租户全部；</li>
     *   <li>企业管理员：**本机构全部**（含机构直属 {@code department_id=0} 的项目 ——
     *       只看部门集合会把机构直属项目漏掉，导致「自己建的项目自己打不开」）；</li>
     *   <li>部门负责人/成员：其负责或所属部门的项目，或本人参与的项目（BR-15）。</li>
     * </ul>
     */
    public boolean canSee(AuthUser user, PmProject p) {
        if (PermissionCatalog.isPlatformAdmin(user)
                || OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)) {
            return true;
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_ORG_ADMIN)) {
            Long inst = guard.resolveInstitutionId(user.getUserId());
            // 机构管理员管辖本机构（含机构直属）。inst 解析不到时回落到部门集合判定，避免越权放行。
            if (inst != null && Objects.equals(p.getInstitutionId(), inst)) {
                return true;
            }
        }
        if (visibleDepartmentIds(user, p.getTenantId()).contains(p.getDepartmentId())) {
            return true;
        }
        return memberProjectIds(p.getTenantId(), user.getUserId()).contains(p.getId());
    }

    /** 是否可管理项目本身（改信息 / 改状态 / 软删 / 绑解仓库）。 */
    public boolean canManage(AuthUser user, PmProject p) {
        if (PermissionCatalog.isPlatformAdmin(user)) {
            return false;
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)
                || OrgGuard.hasRole(user, OrgGuard.ROLE_ORG_ADMIN)) {
            return true;
        }
        PmProjectMember mine = myMembership(p.getTenantId(), p.getId(), user.getUserId());
        if (mine != null && PmProjectRoles.canManageProject(mine.getRoleCode())) {
            return true;
        }
        // 负责人（即使成员行缺失）与创建者兜底
        if (Objects.equals(p.getCreatedBy(), user.getUserId())) {
            return true;
        }
        return guard.ledDepartments(user.getUserId()).stream()
                .anyMatch(d -> Objects.equals(d.getId(), p.getDepartmentId()));
    }

    /** 当前用户在某租户内可见的部门集合。 */
    public Set<Long> visibleDepartmentIds(AuthUser user, Long tenantId) {
        if (PermissionCatalog.isPlatformAdmin(user)
                || OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)) {
            return departmentMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                            .eq(OrgDepartment::getTenantId, tenantId)).stream()
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
        Set<Long> ids = new HashSet<>();
        guard.ledDepartments(user.getUserId()).forEach(d -> ids.add(d.getId()));
        if (user.getDepartmentId() != null) {
            ids.add(user.getDepartmentId());
        }
        return ids;
    }

    /** 我参与的项目 id（BR-15「我是成员」）。 */
    public Set<Long> memberProjectIds(Long tenantId, Long userId) {
        if (userId == null) {
            return Set.of();
        }
        return memberMapper.selectList(new LambdaQueryWrapper<PmProjectMember>()
                        .eq(PmProjectMember::getTenantId, tenantId)
                        .eq(PmProjectMember::getUserId, userId)).stream()
                .map(PmProjectMember::getProjectId).collect(Collectors.toSet());
    }

    /** 我在某项目里的成员记录（含项目角色）。 */
    public PmProjectMember myMembership(Long tenantId, Long projectId, Long userId) {
        if (userId == null) {
            return null;
        }
        List<PmProjectMember> rows = memberMapper.selectList(new LambdaQueryWrapper<PmProjectMember>()
                .eq(PmProjectMember::getTenantId, tenantId)
                .eq(PmProjectMember::getProjectId, projectId)
                .eq(PmProjectMember::getUserId, userId)
                .last("LIMIT 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 在册员工校验（BR-03）。 */
    public OrgMember requireActiveMember(Long tenantId, Long memberId) {
        OrgMember m = orgMemberMapper.selectById(memberId);
        if (m == null || !Objects.equals(m.getTenantId(), tenantId)) {
            throw BizException.badRequest("该员工不存在或不属于当前企业");
        }
        if (!"ACTIVE".equals(m.getStatus())) {
            throw BizException.badRequest("该员工不在册（状态：" + m.getStatus() + "）");
        }
        return m;
    }

    private void requirePermission(AuthUser user, String permission) {
        if (!PermissionCatalog.holds(user, permission)) {
            throw BizException.forbidden("当前角色无权访问「项目管理」");
        }
    }

    private void insertMember(PmProject p, Long memberId, String roleCode, Long actorId) {
        OrgMember m = requireActiveMember(p.getTenantId(), memberId);
        PmProjectMember pm = new PmProjectMember();
        pm.setTenantId(p.getTenantId());
        pm.setProjectId(p.getId());
        pm.setMemberId(memberId);
        pm.setUserId(m.getUserId());
        pm.setRoleCode(roleCode);
        pm.setRepoSyncStatus(PmProjectType.isDev(p.getProjectType()) ? "PENDING" : "NA");
        pm.setJoinedAt(LocalDate.now());
        pm.setCreatedBy(actorId);
        pm.setCreatedAt(LocalDateTime.now());
        memberMapper.insert(pm);
    }

    /**
     * 建「项目文档」根目录（用户关键词：每个项目创建一个文档目录）。
     *
     * <p>新项目在立项时即建目录；历史项目由 {@code PmDocService.ensureProjectRoot}
     * 在首次打开文档页时补齐。这里直接写 mapper（不调 PmDocService），避免与其形成注入环。</p>
     */
    private void createProjectRootFolder(PmProject p, Long actorId) {
        cn.aioa.project.entity.PmFolder f = new cn.aioa.project.entity.PmFolder();
        f.setTenantId(p.getTenantId());
        f.setScope(cn.aioa.project.entity.PmFolder.SCOPE_PROJECT);
        f.setProjectId(p.getId());
        f.setParentId(cn.aioa.project.entity.PmFolder.ROOT_PARENT);
        f.setName(PmDocService.PROJECT_ROOT_NAME);
        f.setStorageKind("LOCAL");
        f.setCreatedBy(actorId);
        f.setCreatedAt(LocalDateTime.now());
        pmFolderMapper.insert(f);
        f.setPath("/" + f.getId() + "/");
        pmFolderMapper.updateById(f);
    }

    private Long resolveInstitutionForCreate(AuthUser user, Long tenantId, Long departmentId) {
        if (departmentId != null && departmentId > 0) {
            OrgDepartment d = departmentMapper.selectById(departmentId);
            if (d == null || !Objects.equals(d.getTenantId(), tenantId) || d.getDeletedAt() != null) {
                throw BizException.badRequest("归属部门不存在或不属于当前企业");
            }
            return d.getInstitutionId();
        }
        // 机构直属：机构取用户所在机构；平台/租户管理员未归属机构时取 0（平台级项目）
        Long inst = guard.resolveInstitutionId(user.getUserId());
        return inst == null ? 0L : inst;
    }

    private Map<Long, long[]> taskStats(List<Long> projectIds) {
        Map<Long, long[]> out = new HashMap<>();
        if (projectIds.isEmpty()) {
            return out;
        }
        List<PmTask> tasks = taskMapper.selectList(new LambdaQueryWrapper<PmTask>()
                .in(PmTask::getProjectId, projectIds)
                .select(PmTask::getProjectId, PmTask::getStatus));
        for (PmTask t : tasks) {
            long[] c = out.computeIfAbsent(t.getProjectId(), k -> new long[2]);
            c[0]++;
            if (cn.aioa.project.support.PmTaskStatus.DONE.equals(t.getStatus())) {
                c[1]++;
            }
        }
        return out;
    }

    private Map<Long, Long> memberCounts(List<Long> projectIds) {
        Map<Long, Long> out = new HashMap<>();
        if (projectIds.isEmpty()) {
            return out;
        }
        List<PmProjectMember> rows = memberMapper.selectList(new LambdaQueryWrapper<PmProjectMember>()
                .in(PmProjectMember::getProjectId, projectIds)
                .select(PmProjectMember::getProjectId));
        for (PmProjectMember r : rows) {
            out.merge(r.getProjectId(), 1L, Long::sum);
        }
        return out;
    }

    private String ownerName(Long tenantId, Long ownerMemberId) {
        if (ownerMemberId == null) {
            return null;
        }
        OrgMember m = orgMemberMapper.selectById(ownerMemberId);
        return m == null ? null : m.getName();
    }

    // ---- 入参解析（与 GiteeProjectService 同风格：宽松解析、明确报错） ----
    // public：控制器与其他服务共用同一套解析口径，避免各处自己写一遍（口径漂移的经典入口）。

    public static String str(Object o) {
        return o == null ? null : String.valueOf(o).trim();
    }

    public static Long asLong(Object o) {
        if (o == null || "".equals(o)) {
            return null;
        }
        if (o instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(o).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public static BigDecimal decimal(Object o) {
        if (o == null || "".equals(o)) {
            return BigDecimal.ZERO;
        }
        if (o instanceof Number n) {
            return BigDecimal.valueOf(n.doubleValue());
        }
        try {
            return new BigDecimal(String.valueOf(o).trim());
        } catch (NumberFormatException e) {
            throw BizException.badRequest("金额格式不正确：" + o);
        }
    }

    public static LocalDate date(Object o) {
        if (o == null || "".equals(o)) {
            return null;
        }
        try {
            return LocalDate.parse(String.valueOf(o).trim());
        } catch (Exception e) {
            throw BizException.badRequest("日期格式应为 yyyy-MM-dd：" + o);
        }
    }
}
