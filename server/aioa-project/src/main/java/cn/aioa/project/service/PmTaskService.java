package cn.aioa.project.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.entity.PmProject;
import cn.aioa.project.entity.PmProjectMember;
import cn.aioa.project.entity.PmTask;
import cn.aioa.project.mapper.PmProjectMemberMapper;
import cn.aioa.project.mapper.PmRepoBindMapper;
import cn.aioa.project.mapper.PmTaskMapper;
import cn.aioa.project.support.PmProjectRoles;
import cn.aioa.project.support.PmProjectStatus;
import cn.aioa.project.support.PmProjectType;
import cn.aioa.project.support.PmTaskStatus;
import cn.aioa.project.support.ProjectTypeGuard;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 项目任务（BR-01 / BR-10 / BR-12）。
 *
 * <p><b>仓库关联只对开发项目开放</b>：业务项目写 {@code repo_*} 一律 400（BR-01），
 * 且 {@code repoId} 必须指向**本项目已绑定**的仓库 —— 否则任务会链到别的项目的仓库，
 * 界面上点进去看到的是别人的代码。</p>
 *
 * <p><b>状态机</b>：转移白名单在 {@link PmTaskStatus#canTransition}，前端拦截非法拖拽 + 后端兜底，
 * 两处同源。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PmTaskService {

    private final PmTaskMapper taskMapper;
    private final PmProjectMemberMapper memberMapper;
    private final PmRepoBindMapper repoBindMapper;
    private final PmProjectService projectService;
    private final OrgGuard guard;

    // ======================================================================
    // 查询
    // ======================================================================

    /** 任务列表（可按状态 / 负责人 / 关键字筛选）。 */
    public Map<String, Object> list(AuthUser user, Long projectId, String status,
                                    Long assigneeMemberId, String keyword) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        List<PmTask> tasks = taskMapper.selectList(new LambdaQueryWrapper<PmTask>()
                .eq(PmTask::getTenantId, p.getTenantId())
                .eq(PmTask::getProjectId, projectId)
                .eq(StringUtils.hasText(status), PmTask::getStatus, status)
                .eq(assigneeMemberId != null, PmTask::getAssigneeMemberId, assigneeMemberId)
                .like(StringUtils.hasText(keyword), PmTask::getTitle, keyword)
                .orderByDesc(PmTask::getId));

        List<Map<String, Object>> items = tasks.stream().map(t -> toView(p, t)).collect(Collectors.toList());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("total", items.size());
        out.put("canManage", canManageTask(user, p));
        out.put("myRole", myRole(user, p));
        out.put("isDev", PmProjectType.isDev(p.getProjectType()));
        // 看板列：仅在开发项目里附带仓库列，业务项目不出现（前端据此渲染，避免死渲染仓库列）
        out.put("statusOptions", List.of(
                Map.of("value", PmTaskStatus.TODO, "label", PmTaskStatus.label(PmTaskStatus.TODO)),
                Map.of("value", PmTaskStatus.DOING, "label", PmTaskStatus.label(PmTaskStatus.DOING)),
                Map.of("value", PmTaskStatus.BLOCKED, "label", PmTaskStatus.label(PmTaskStatus.BLOCKED)),
                Map.of("value", PmTaskStatus.DONE, "label", PmTaskStatus.label(PmTaskStatus.DONE)),
                Map.of("value", PmTaskStatus.CANCELED, "label", PmTaskStatus.label(PmTaskStatus.CANCELED))));
        return out;
    }

    // ======================================================================
    // 写
    // ======================================================================

    /** 建任务。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> create(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, true);
        requireTaskManager(user, p);
        assertWritable(p);

        String title = PmProjectService.str(body.get("title"));
        if (!StringUtils.hasText(title)) {
            throw BizException.badRequest("任务标题不能为空");
        }

        Long repoId = PmProjectService.asLong(body.get("repoId"));
        String issueNo = PmProjectService.str(body.get("repoIssueNo"));
        String branch = PmProjectService.str(body.get("repoBranch"));
        String commit = PmProjectService.str(body.get("repoCommitSha"));

        // BR-01：业务项目不接受任何仓库配置
        ProjectTypeGuard.assertRepoAllowed(p.getProjectType(),
                ProjectTypeGuard.taskHasRepoConfig(repoId, issueNo, branch, commit));
        // BR-12：仓库字段成对
        ProjectTypeGuard.assertRepoPairing(repoId, issueNo, branch, commit);
        if (repoId != null) {
            assertRepoBoundToProject(p, repoId);
        }

        PmTask t = new PmTask();
        t.setTenantId(p.getTenantId());
        t.setProjectId(projectId);
        t.setParentId(PmProjectService.asLong(body.get("parentId")));
        if (t.getParentId() != null) {
            assertParentInProject(p, t.getParentId(), null);
        }
        t.setTitle(title);
        t.setDescription(PmProjectService.str(body.get("description")));
        t.setStatus(PmTaskStatus.TODO);
        String priority = PmProjectService.str(body.get("priority"));
        if (priority != null && !PmTaskStatus.isValidPriority(priority)) {
            throw BizException.badRequest("未知优先级：" + priority);
        }
        t.setPriority(priority == null ? "MEDIUM" : priority);
        t.setAssigneeMemberId(assignee(user, p, body.get("assigneeMemberId")));
        t.setStartDate(PmProjectService.date(body.get("startDate")));
        t.setDueDate(PmProjectService.date(body.get("dueDate")));
        t.setProgress(clampProgress(body.get("progress")));
        t.setRepoId(repoId);
        t.setRepoIssueNo(repoId == null ? null : issueNo);
        t.setRepoBranch(repoId == null ? null : branch);
        t.setRepoCommitSha(repoId == null ? null : commit);
        t.setCreatedBy(user.getUserId());
        t.setCreatedAt(LocalDateTime.now());
        taskMapper.insert(t);
        return singleView(p, t.getId());
    }

    /** 改任务（含 BR-01/BR-12 守卫）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> update(AuthUser user, Long projectId, Long taskId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, true);
        PmTask t = requireTask(p, taskId);
        requireTaskEditor(user, p, t);
        assertWritable(p);

        boolean repoKeysPresent = body.containsKey("repoId") || body.containsKey("repoIssueNo")
                || body.containsKey("repoBranch") || body.containsKey("repoCommitSha");
        if (repoKeysPresent) {
            requireRepoEditor(user, p);
        }

        if (body.containsKey("title")) {
            String title = PmProjectService.str(body.get("title"));
            if (!StringUtils.hasText(title)) {
                throw BizException.badRequest("任务标题不能为空");
            }
            t.setTitle(title);
        }
        if (body.containsKey("description")) {
            t.setDescription(PmProjectService.str(body.get("description")));
        }
        if (body.containsKey("priority")) {
            String priority = PmProjectService.str(body.get("priority"));
            if (priority != null && !PmTaskStatus.isValidPriority(priority)) {
                throw BizException.badRequest("未知优先级：" + priority);
            }
            t.setPriority(priority);
        }
        if (body.containsKey("assigneeMemberId")) {
            t.setAssigneeMemberId(assignee(user, p, body.get("assigneeMemberId")));
        }
        if (body.containsKey("startDate")) {
            t.setStartDate(PmProjectService.date(body.get("startDate")));
        }
        if (body.containsKey("dueDate")) {
            t.setDueDate(PmProjectService.date(body.get("dueDate")));
        }
        if (body.containsKey("progress")) {
            t.setProgress(clampProgress(body.get("progress")));
        }
        if (body.containsKey("parentId")) {
            Long parentId = PmProjectService.asLong(body.get("parentId"));
            if (parentId != null) {
                assertParentInProject(p, parentId, taskId);
            }
            t.setParentId(parentId);
        }

        if (repoKeysPresent) {
            Long repoId = body.containsKey("repoId")
                    ? PmProjectService.asLong(body.get("repoId")) : t.getRepoId();
            String issueNo = body.containsKey("repoIssueNo")
                    ? PmProjectService.str(body.get("repoIssueNo")) : t.getRepoIssueNo();
            String branch = body.containsKey("repoBranch")
                    ? PmProjectService.str(body.get("repoBranch")) : t.getRepoBranch();
            String commit = body.containsKey("repoCommitSha")
                    ? PmProjectService.str(body.get("repoCommitSha")) : t.getRepoCommitSha();

            ProjectTypeGuard.assertRepoAllowed(p.getProjectType(),
                    ProjectTypeGuard.taskHasRepoConfig(repoId, issueNo, branch, commit));
            // 清空仓库（repoId=null）时允许其它字段一起清掉，故只在仍有 repoId 时校验成对
            ProjectTypeGuard.assertRepoPairing(repoId, issueNo, branch, commit);
            if (repoId != null) {
                assertRepoBoundToProject(p, repoId);
            }
            t.setRepoId(repoId);
            t.setRepoIssueNo(repoId == null ? null : issueNo);
            t.setRepoBranch(repoId == null ? null : branch);
            t.setRepoCommitSha(repoId == null ? null : commit);
        }

        t.setUpdatedAt(LocalDateTime.now());
        taskMapper.updateById(t);
        return singleView(p, taskId);
    }

    /** 改任务状态（走 {@link PmTaskStatus#canTransition} 白名单）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> transition(AuthUser user, Long projectId, Long taskId, String status) {
        PmProject p = projectService.requireVisible(user, projectId, true);
        PmTask t = requireTask(p, taskId);
        requireTaskEditor(user, p, t);
        assertWritable(p);

        if (!PmTaskStatus.isValid(status)) {
            throw BizException.badRequest("未知任务状态：" + status);
        }
        if (!PmTaskStatus.canTransition(t.getStatus(), status)) {
            throw BizException.badRequest("不允许从 " + t.getStatus() + " 变更为 " + status
                    + (PmTaskStatus.isTerminal(t.getStatus()) ? "（已完成的任务不可回退）" : ""));
        }
        t.setStatus(status);
        // 置完成即进度 100（避免「已完成但进度 60%」的自相矛盾展示）
        if (PmTaskStatus.DONE.equals(status)) {
            t.setProgress(100);
        }
        t.setUpdatedAt(LocalDateTime.now());
        taskMapper.updateById(t);
        return singleView(p, taskId);
    }

    /** 删任务（软删）。父任务删除前要求子任务已全部完成或取消。 */
    @Transactional(rollbackFor = Exception.class)
    public void delete(AuthUser user, Long projectId, Long taskId) {
        PmProject p = projectService.requireVisible(user, projectId, true);
        PmTask t = requireTask(p, taskId);
        requireTaskManager(user, p);
        assertWritable(p);

        List<PmTask> children = taskMapper.selectList(new LambdaQueryWrapper<PmTask>()
                .eq(PmTask::getTenantId, p.getTenantId())
                .eq(PmTask::getParentId, taskId));
        List<String> openChildren = children.stream()
                .filter(c -> !PmTaskStatus.DONE.equals(c.getStatus())
                        && !PmTaskStatus.CANCELED.equals(c.getStatus()))
                .map(PmTask::getTitle).toList();
        if (!openChildren.isEmpty()) {
            throw BizException.badRequest("存在未完成子任务（" + String.join("、", openChildren)
                    + "），请先完成或取消后再删除父任务");
        }
        taskMapper.deleteById(taskId);
    }

    // ======================================================================
    // 内部
    // ======================================================================

    private Map<String, Object> singleView(PmProject p, Long taskId) {
        PmTask t = taskMapper.selectById(taskId);
        if (t == null) {
            throw BizException.notFound("任务不存在");
        }
        return toView(p, t);
    }

    private Map<String, Object> toView(PmProject p, PmTask t) {
        Map<String, Object> x = new LinkedHashMap<>();
        x.put("id", t.getId());
        x.put("projectId", t.getProjectId());
        x.put("parentId", t.getParentId());
        x.put("title", t.getTitle());
        x.put("description", t.getDescription());
        x.put("status", t.getStatus());
        x.put("statusLabel", PmTaskStatus.label(t.getStatus()));
        x.put("priority", t.getPriority());
        x.put("assigneeMemberId", t.getAssigneeMemberId());
        x.put("startDate", t.getStartDate());
        x.put("dueDate", t.getDueDate());
        x.put("progress", t.getProgress());
        // 仓库字段：业务项目一律回 null（前端据此不渲染仓库列，与后端守卫同口径）
        boolean dev = PmProjectType.isDev(p.getProjectType());
        x.put("repoId", dev ? t.getRepoId() : null);
        x.put("repoIssueNo", dev ? t.getRepoIssueNo() : null);
        x.put("repoBranch", dev ? t.getRepoBranch() : null);
        x.put("repoCommitSha", dev ? t.getRepoCommitSha() : null);
        x.put("createdAt", t.getCreatedAt());
        return x;
    }

    private PmTask requireTask(PmProject p, Long taskId) {
        PmTask t = taskMapper.selectById(taskId);
        if (t == null || !Objects.equals(t.getTenantId(), p.getTenantId())
                || !Objects.equals(t.getProjectId(), p.getId())) {
            throw BizException.notFound("任务不存在");
        }
        return t;
    }

    /** 项目处于只读终态（已结项/已归档）时禁止再写任务。 */
    private void assertWritable(PmProject p) {
        if (PmProjectStatus.isReadOnly(p.getStatus())) {
            throw BizException.badRequest("项目已" + ("CLOSED".equals(p.getStatus()) ? "结项" : "归档")
                    + "，不能再修改任务");
        }
    }

    private Long assignee(AuthUser user, PmProject p, Object raw) {
        Long memberId = PmProjectService.asLong(raw);
        if (memberId == null) {
            return null;
        }
        // 负责人必须是本项目成员（否则任务会指派给一个看不到这个项目的人）
        Long inProject = memberMapper.selectCount(new LambdaQueryWrapper<PmProjectMember>()
                .eq(PmProjectMember::getProjectId, p.getId())
                .eq(PmProjectMember::getMemberId, memberId));
        if (inProject == null || inProject == 0) {
            throw BizException.badRequest("任务负责人必须是本项目成员，请先将其加入项目");
        }
        return memberId;
    }

    private void assertRepoBoundToProject(PmProject p, Long repoId) {
        long bound = repoBindMapper.listByProject(p.getTenantId(), p.getId()).stream()
                .filter(r -> Objects.equals(PmProjectService.asLong(r.get("id")), repoId))
                .count();
        if (bound == 0) {
            throw BizException.badRequest("该仓库未绑定到本项目，请先在「仓库」页签绑定后再关联任务");
        }
    }

    private void assertParentInProject(PmProject p, Long parentId, Long selfId) {
        if (Objects.equals(parentId, selfId)) {
            throw BizException.badRequest("任务不能以自己为父任务");
        }
        PmTask parent = taskMapper.selectById(parentId);
        if (parent == null || !Objects.equals(parent.getProjectId(), p.getId())) {
            throw BizException.badRequest("父任务不存在或不属于本项目");
        }
        if (parent.getParentId() != null) {
            throw BizException.badRequest("子任务最多两级，不能挂在子任务下");
        }
    }

    private Integer clampProgress(Object raw) {
        Long v = PmProjectService.asLong(raw);
        if (v == null) {
            return 0;
        }
        if (v < 0 || v > 100) {
            throw BizException.badRequest("进度必须在 0-100 之间");
        }
        return v.intValue();
    }

    private void requireTaskManager(AuthUser user, PmProject p) {
        if (canManageTask(user, p)) {
            return;
        }
        throw BizException.forbidden("仅项目负责人/项目经理/开发或机构管理员及以上可管理任务");
    }

    /** 改「任务本身」的权限：管理者，或（成员）改自己负责的任务。 */
    private void requireTaskEditor(AuthUser user, PmProject p, PmTask t) {
        if (canManageTask(user, p)) {
            return;
        }
        String myRole = myRole(user, p);
        if (PmProjectRoles.canUpdateOwnTask(myRole)) {
            PmProjectMember mine = projectService.myMembership(p.getTenantId(), p.getId(), user.getUserId());
            if (mine != null && Objects.equals(mine.getMemberId(), t.getAssigneeMemberId())) {
                return;
            }
        }
        throw BizException.forbidden("仅任务负责人或项目管理者可修改该任务");
    }

    private void requireRepoEditor(AuthUser user, PmProject p) {
        if (canManageTask(user, p)) {
            return;
        }
        throw BizException.forbidden("仅项目负责人/项目经理/开发可修改任务的仓库关联");
    }

    private boolean canManageTask(AuthUser user, PmProject p) {
        if (cn.aioa.security.PermissionCatalog.isPlatformAdmin(user)) {
            return false;
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)
                || OrgGuard.hasRole(user, OrgGuard.ROLE_ORG_ADMIN)) {
            return true;
        }
        return PmProjectRoles.canManageTask(myRole(user, p));
    }

    private String myRole(AuthUser user, PmProject p) {
        PmProjectMember mine = projectService.myMembership(p.getTenantId(), p.getId(), user.getUserId());
        return mine == null ? null : mine.getRoleCode();
    }
}
