package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.AgentWorkerRun;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AgentWorkerRunMapper;
import cn.aioa.resource.service.ContentReviewService;
import cn.aioa.resource.service.WorkerScheduleService;
import cn.aioa.security.PermissionCatalog;
import cn.aioa.resource.support.ScheduleTimeSupport;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Objects;

/**
 * 数字员工 —— 管理端维护（V1.2 新增；V15 增加定时任务；V33 权限归属对齐）：
 *   GET/POST/PUT/DELETE /api/v1/admin/workers[/{id}]、POST /{id}/toggle
 *   GET  /{id}/runs          执行记录（真实运行留痕）
 *   POST /{id}/run           立即执行一次（手动触发，真实调模型）
 *
 * <h3>创建/管理权限归属（V33 明确）</h3>
 * <p>此前本控制器只认 {@code ROLE_ADMIN || ROLE_TENANT_ADMIN}，与
 * {@code /api/v1/workers}（走 {@link PermissionCatalog}，已含企业管理员与部门负责人）
 * 口径打架：企业管理员在用户端能建、在管理端却被 403。现统一以权限码判定，
 * 数据范围按角色收紧：</p>
 * <table>
 *   <tr><th>角色</th><th>可创建</th><th>可管理范围</th></tr>
 *   <tr><td>系统管理员</td><td>✅</td><td>本租户上下文（tenant 0 = 全局模板）</td></tr>
 *   <tr><td>租户管理员</td><td>✅</td><td>本租户全部</td></tr>
 *   <tr><td>企业管理员</td><td>✅</td><td>本机构（institution_id 相等）</td></tr>
 *   <tr><td>部门负责人</td><td>✅</td><td>已分发到本部门的（visible_scope=DEPT）</td></tr>
 *   <tr><td>机构成员 / 普通用户</td><td>❌</td><td>—</td></tr>
 * </table>
 */
@RestController
@RequestMapping("/api/v1/admin/workers")
@RequiredArgsConstructor
public class AdminWorkerController {

    private final AgentWorkerMapper workerMapper;
    private final AgentWorkerRunMapper runMapper;
    private final WorkerScheduleService scheduleService;
    private final ContentReviewService reviewService;

    /**
     * 数字员工管理权限判定（唯一入口）。
     *
     * @param permission {@link PermissionCatalog#WORKER_CREATE} 或 {@link PermissionCatalog#WORKER_MANAGE}
     * @param action     动作名，用于拼出可读的 403 提示
     */
    private AuthUser requireManager(String permission, String action) {
        AuthUser user = AuthUserContext.require();
        if (!PermissionCatalog.holds(user, permission)) {
            throw BizException.forbidden(action + "需要数字员工管理权限（"
                    + PermissionCatalog.rolesText(permission) + "）；当前账号角色为「"
                    + String.join("、", user.getRoles() == null ? List.of() : user.getRoles()) + "」。"
                    + "使用数字员工与提交业务申请不受此限制。");
        }
        return user;
    }

    /** 企业管理员（且不是平台/租户管理员）：数据范围收紧到本机构。 */
    private static boolean institutionScoped(AuthUser user) {
        return PermissionCatalog.hasRole(user, PermissionCatalog.ROLE_ORG_ADMIN)
                && !PermissionCatalog.hasRole(user, PermissionCatalog.ROLE_TENANT_ADMIN)
                && !PermissionCatalog.isPlatformAdmin(user);
    }

    /** 作用域内的数字员工列表。 */
    private List<AgentWorker> listScoped(AuthUser user) {
        List<AgentWorker> all = workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                .eq(AgentWorker::getTenantId, user.getTenantId())
                .orderByAsc(AgentWorker::getId));
        if (PermissionCatalog.isDeptLeaderOnly(user)) {
            return all.stream().filter(w -> deptScopedTo(w, user.getDepartmentId())).toList();
        }
        if (institutionScoped(user)) {
            return all.stream().filter(w -> Objects.equals(w.getInstitutionId(), user.getInstitutionId())).toList();
        }
        return all;
    }

    private AgentWorker requireOwned(AuthUser user, Long id) {
        AgentWorker cur = workerMapper.selectById(id);
        if (cur == null || !Objects.equals(user.getTenantId(), cur.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        if (PermissionCatalog.isDeptLeaderOnly(user)) {
            if (!deptScopedTo(cur, user.getDepartmentId())) {
                throw BizException.forbidden("部门负责人只能管理已分发到本部门的数字员工；"
                        + "该数字员工不在您本部门（" + user.getDepartmentId() + "）的可见范围内");
            }
            return cur;
        }
        if (institutionScoped(user) && !Objects.equals(cur.getInstitutionId(), user.getInstitutionId())) {
            throw BizException.forbidden("企业管理员只能管理本机构（institutionId="
                    + user.getInstitutionId() + "）的数字员工");
        }
        return cur;
    }

    /**
     * 新建时的作用域落库。
     *
     * <p>企业管理员创建的数字员工自动打上本机构标记（避免跨机构可见）；
     * 部门负责人进一步强制锁定到本部门，不接受前端入参（防止改包自我提权）。</p>
     */
    private static void applyScopeOnCreate(AgentWorker w, AuthUser user) {
        if (institutionScoped(user)) {
            w.setInstitutionId(user.getInstitutionId());
        }
        if (PermissionCatalog.isDeptLeaderOnly(user)) {
            Long deptId = user.getDepartmentId();
            if (deptId == null) {
                throw BizException.forbidden("您的账号未绑定部门，无法创建部门级数字员工");
            }
            w.setInstitutionId(user.getInstitutionId());
            w.setVisibleScope("DEPT");
            w.setDeptIds("[" + deptId + "]");
        }
    }

    /** 该数字员工是否被显式分发到指定部门（{@code visible_scope=DEPT} 且 dept_ids 含该部门）。 */
    private static boolean deptScopedTo(AgentWorker w, Long deptId) {
        if (deptId == null || !"DEPT".equals(w.getVisibleScope())) {
            return false;
        }
        String ids = w.getDeptIds();
        if (ids == null || ids.isBlank()) {
            return false;
        }
        String wanted = deptId.toString();
        for (String part : ids.replaceAll("[^0-9,]", "").split(",")) {
            if (wanted.equals(part)) {
                return true;
            }
        }
        return false;
    }

    @GetMapping
    public ApiResponse<List<AgentWorker>> list() {
        AuthUser user = requireManager(PermissionCatalog.WORKER_MANAGE, "查看数字员工列表");
        return ApiResponse.ok(listScoped(user));
    }

    @PostMapping
    public ApiResponse<AgentWorker> create(@RequestBody AgentWorker body) {
        AuthUser user = requireManager(PermissionCatalog.WORKER_CREATE, "创建数字员工");
        if (body.getName() == null || body.getName().isBlank()) {
            throw BizException.badRequest("数字员工名称不能为空");
        }
        validateScheduleTime(body.getScheduleTime());
        body.setId(null);
        body.setTenantId(user.getTenantId());
        applyScopeOnCreate(body, user);
        body.setCreatedBy(user.getUserId());
        body.setCreatedAt(LocalDateTime.now());
        body.setUpdatedAt(LocalDateTime.now());
        if (body.getEnabled() == null) body.setEnabled(1);
        if (body.getStatus() == null) body.setStatus(AgentWorker.STATUS_RUNNING);
        if (body.getIcon() == null || body.getIcon().isBlank()) body.setIcon("bot");
        body.setScheduleTime(normalizeScheduleTime(body.getScheduleTime()));
        // V34：租户管理员在管理端创建的内容同样需平台管理员审核（与用户端同一口径，避免绕行）
        body.setAuditStatus(reviewService.initialStatus(user));
        workerMapper.insert(body);
        return ApiResponse.ok(body);
    }

    @PutMapping("/{id}")
    public ApiResponse<AgentWorker> update(@PathVariable Long id, @RequestBody AgentWorker body) {
        AuthUser user = requireManager(PermissionCatalog.WORKER_MANAGE, "修改数字员工");
        AgentWorker cur = requireOwned(user, id);
        validateScheduleTime(body.getScheduleTime());
        body.setId(id);
        body.setTenantId(cur.getTenantId());
        // 归属机构 / 可见范围属于管控字段，不随表单回传而丢失或改变
        body.setInstitutionId(cur.getInstitutionId());
        body.setVisibleScope(cur.getVisibleScope());
        body.setDeptIds(cur.getDeptIds());
        body.setCreatedBy(cur.getCreatedBy());
        body.setCreatedAt(cur.getCreatedAt());
        body.setUpdatedAt(LocalDateTime.now());
        body.setScheduleTime(normalizeScheduleTime(body.getScheduleTime()));
        workerMapper.updateById(body);
        return ApiResponse.ok(body);
    }

    @PostMapping("/{id}/toggle")
    public ApiResponse<AgentWorker> toggle(@PathVariable Long id) {
        AuthUser user = requireManager(PermissionCatalog.WORKER_MANAGE, "启停数字员工");
        AgentWorker cur = requireOwned(user, id);
        boolean next = Integer.valueOf(0).equals(cur.getEnabled());
        cur.setEnabled(next ? 1 : 0);
        cur.setStatus(next ? AgentWorker.STATUS_RUNNING : AgentWorker.STATUS_IDLE);
        cur.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(cur);
        return ApiResponse.ok(cur);
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Boolean> delete(@PathVariable Long id) {
        AuthUser user = requireManager(PermissionCatalog.WORKER_MANAGE, "删除数字员工");
        requireOwned(user, id);
        return ApiResponse.ok(workerMapper.deleteById(id) > 0);
    }

    /** 执行记录（真实运行留痕，倒序）。 */
    @GetMapping("/{id}/runs")
    public ApiResponse<List<AgentWorkerRun>> runs(@PathVariable Long id,
                                                  @RequestParam(name = "limit", defaultValue = "20") int limit) {
        AuthUser user = requireManager(PermissionCatalog.WORKER_MANAGE, "查看执行记录");
        AgentWorker cur = requireOwned(user, id);
        return ApiResponse.ok(runMapper.selectList(new LambdaQueryWrapper<AgentWorkerRun>()
                .eq(AgentWorkerRun::getWorkerId, cur.getId())
                .orderByDesc(AgentWorkerRun::getStartedAt)
                .last("limit " + Math.max(1, Math.min(limit, 100)))));
    }

    /** 立即执行一次（手动触发，真实调模型并落记录、发通知）。 */
    @PostMapping("/{id}/run")
    public ApiResponse<AgentWorkerRun> run(@PathVariable Long id) {
        AuthUser user = requireManager(PermissionCatalog.WORKER_MANAGE, "立即执行数字员工");
        AgentWorker cur = requireOwned(user, id);
        return ApiResponse.ok(scheduleService.runNow(cur, AgentWorkerRun.TRIGGER_MANUAL));
    }

    private void validateScheduleTime(String time) {
        ScheduleTimeSupport.validate(time);
    }

    private String normalizeScheduleTime(String time) {
        return ScheduleTimeSupport.normalize(time);
    }
}
