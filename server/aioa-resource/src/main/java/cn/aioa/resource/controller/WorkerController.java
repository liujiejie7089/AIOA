package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.AgentWorkerRun;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AgentWorkerRunMapper;
import cn.aioa.resource.service.WorkerScheduleService;
import cn.aioa.resource.support.PermissionCatalog;
import cn.aioa.resource.support.ScheduleTimeSupport;
import cn.aioa.resource.support.WorkerRole;
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

/**
 * 数字员工（V1.2 新增；V18 补全创建/编辑闭环）：
 *
 * <pre>
 *   GET    /api/v1/workers              本租户数字员工列表
 *   POST   /api/v1/workers              创建（会话内「一句话创建」确认后调用）
 *   PUT    /api/v1/workers/{id}         原地更新（编辑：名称/职责/执行时刻/任务内容/计划说明）
 *   POST   /api/v1/workers/{id}/toggle  启用 / 停用（历史产出保留）
 *   GET    /api/v1/workers/{id}/runs    执行记录（真实运行留痕）
 *   POST   /api/v1/workers/{id}/run     立即执行一次（手动触发）
 *   DELETE /api/v1/workers/{id}         删除（逻辑删除，历史留痕保留）
 * </pre>
 *
 * <p>关键约定：创建/更新时 {@code scheduleTime}(执行时刻 HH:mm) 与 {@code taskPrompt}(任务内容)
 * 必须落库，否则 {@link WorkerScheduleService} 的定时扫描永远匹配不到该员工。
 * 未配置执行时刻时状态为「待配置」而非「运行中」，避免「看起来在跑、实际从不执行」的误导。</p>
 *
 * <h3>操作范围权限矩阵（V22）</h3>
 * <pre>
 *   操作                     普通成员   租户管理员   判定点
 *   ---------------------------------------------------------------
 *   查看列表 / 类型目录 / 运行记录   ✓         ✓      任意登录用户（只读）
 *   与该员工建立会话（使用它）       ✓         ✓      ConversationService.bindWorker
 *   创建 / 修改 / 启停 / 立即执行    ✗ 403     ✓      requireAdmin（敏感管理操作）
 *   删除                            ✗ 403     ✓      requireAdmin（敏感管理操作）
 * </pre>
 *
 * <p>「使用数字员工」（例如向请假数字人提交请假申请）对所有成员开放；
 * 「管理数字员工」（创建/改配置/启停/手动执行/删除）仅租户管理员可执行。
 * 越权一律以 403 + 中文提示拦截，**前置拒绝、不落库、不留半成品**。</p>
 */
@RestController
@RequestMapping("/api/v1/workers")
@RequiredArgsConstructor
public class WorkerController {

    private final AgentWorkerMapper workerMapper;
    private final AgentWorkerRunMapper runMapper;
    private final WorkerScheduleService scheduleService;

    public record WorkerView(Long id, String name, String icon, String description, String status,
                             String lastOutput, String schedule, String scheduleTime, String runMode,
                             String taskPrompt,
                             String lastRunAt, boolean on,
                             String workerType, String roleName, String duty, String requiredPermission) {

        static WorkerView from(AgentWorker w) {
            boolean on = !Integer.valueOf(0).equals(w.getEnabled());
            // V22：只有定时型（SCHEDULED）缺执行时刻才判「待配置」；
            // 事件驱动（EVENT）/按需唤起（ON_DEMAND）不需要执行时刻，不再被误标。
            String status = AgentWorker.resolveStatus(w.getRunMode(), w.getScheduleTime(), w.getStatus(), on);
            WorkerRole role = WorkerRole.of(w.getWorkerType());
            return new WorkerView(w.getId(), w.getName(), w.getIcon(), w.getDescription(), status,
                    w.getLastOutput(), w.getScheduleText(), w.getScheduleTime(), w.getRunMode(), w.getTaskPrompt(),
                    w.getLastRunAt() == null ? null : w.getLastRunAt().toString(), on,
                    role.code(), role.displayName(), role.duty(), role.requiredPermission());
        }
    }

    /** 角色类型目录：前端据此渲染可选类型，并置灰当前用户无权限承担的类型。 */
    public record RoleTypeView(String code, String name, String duty, String requiredPermission,
                               String requiredRoles, boolean granted) {

        /**
         * {@code granted} = 当前用户**是否可创建/承担该类型角色**。
         *
         * <p>定为「创建」语义（而不是单纯的「持有权限码」）：创建数字员工属管理员敏感操作，
         * 故普通成员对任何类型都为 false，前端据此置灰类型选择；
         * 管理员则要求同时持有该类型的权限码（如请假类需 {@code approval:leave}）。</p>
         */
        static RoleTypeView of(WorkerRole role, AuthUser user) {
            boolean canCreate = PermissionCatalog.isAdmin(user)
                    && PermissionCatalog.holds(user, role.requiredPermission());
            return new RoleTypeView(role.code(), role.displayName(), role.duty(), role.requiredPermission(),
                    PermissionCatalog.rolesText(role.requiredPermission()), canCreate);
        }
    }

    @GetMapping
    public ApiResponse<List<WorkerView>> list() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                        .eq(AgentWorker::getTenantId, user.getTenantId())
                        .orderByAsc(AgentWorker::getId))
                .stream().map(WorkerView::from).toList());
    }

    /** 角色类型目录（含当前用户是否具备承担该类型的权限）。 */
    @GetMapping("/role-types")
    public ApiResponse<List<RoleTypeView>> roleTypes() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(java.util.Arrays.stream(WorkerRole.values())
                .map(role -> RoleTypeView.of(role, user)).toList());
    }

    @PostMapping
    public ApiResponse<WorkerView> create(@RequestBody AgentWorker body) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "创建数字员工");
        String name = trim(body.getName());
        if (name.isEmpty()) {
            throw BizException.badRequest("数字员工名称不能为空");
        }
        // 角色类型 → 所需权限 → 角色，三者任一处不满足即拒绝创建（V21 权限准入）
        WorkerRole role = resolveRole(body.getWorkerType(), name, body.getDescription());
        requirePermission(user, role);
        AgentWorker w = new AgentWorker();
        w.setTenantId(user.getTenantId());
        w.setName(name);
        w.setWorkerType(role.code());
        w.setIcon(trim(body.getIcon()).isEmpty() ? "bot" : body.getIcon());
        w.setDescription(body.getDescription());
        w.setEnabled(1);

        // 关键：执行时刻与任务内容必须落库，否则定时调度永远不匹配
        String scheduleTime = resolveScheduleTime(body.getScheduleTime());
        String taskPrompt = resolveTaskPrompt(body.getTaskPrompt(), body.getDescription());
        String runMode = resolveRunMode(body.getRunMode(), role.code());
        w.setScheduleTime(scheduleTime);
        w.setTaskPrompt(taskPrompt);
        w.setRunMode(runMode);
        w.setScheduleText(trim(body.getScheduleText()).isEmpty()
                ? (AgentWorker.requiresScheduleTime(runMode)
                ? (scheduleTime == null ? "按计划执行" : "每天 " + scheduleTime + " 自动执行")
                : (AgentWorker.RUN_MODE_EVENT.equals(runMode) ? "触发式（有事件即执行）" : "随时唤起"))
                : body.getScheduleText());
        w.setStatus(AgentWorker.resolveStatus(runMode, scheduleTime, AgentWorker.STATUS_RUNNING, true));
        w.setLastOutput("尚未运行");
        w.setCreatedBy(user.getUserId());
        w.setCreatedAt(LocalDateTime.now());
        w.setUpdatedAt(LocalDateTime.now());
        workerMapper.insert(w);
        return ApiResponse.ok(WorkerView.from(w));
    }

    /** 原地更新：只覆盖本次传入的字段，未传的保持原值（避免编辑丢配置）。 */
    @PutMapping("/{id}")
    public ApiResponse<WorkerView> update(@PathVariable Long id, @RequestBody AgentWorker body) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "修改数字员工");
        AgentWorker cur = requireOwned(user, id);

        if (body.getName() != null) {
            String name = trim(body.getName());
            if (name.isEmpty()) {
                throw BizException.badRequest("数字员工名称不能为空");
            }
            cur.setName(name);
        }
        if (body.getIcon() != null) {
            cur.setIcon(trim(body.getIcon()).isEmpty() ? "bot" : body.getIcon());
        }
        // 角色类型变更 = 承担新类型角色，必须重新通过权限准入
        if (body.getWorkerType() != null && !body.getWorkerType().isBlank()) {
            WorkerRole role = WorkerRole.of(body.getWorkerType());
            requirePermission(user, role);
            cur.setWorkerType(role.code());
        }
        if (body.getDescription() != null) {
            cur.setDescription(body.getDescription());
        }
        if (body.getScheduleText() != null) {
            cur.setScheduleText(body.getScheduleText());
        }
        // 运行模式：显式传入优先；未传保持原值（避免编辑丢配置）
        if (body.getRunMode() != null && !body.getRunMode().isBlank()) {
            cur.setRunMode(resolveRunMode(body.getRunMode(), cur.getWorkerType()));
        }
        // 执行时刻：显式传 null/空串表示清空（回到「待配置」）
        if (body.getScheduleTime() != null) {
            cur.setScheduleTime(resolveScheduleTime(body.getScheduleTime()));
        }
        if (body.getTaskPrompt() != null) {
            cur.setTaskPrompt(resolveTaskPrompt(body.getTaskPrompt(), cur.getDescription()));
        }
        // 状态：启用中按运行模式与执行时刻自动重算；停用保持停用
        if (!Integer.valueOf(0).equals(cur.getEnabled())) {
            cur.setStatus(AgentWorker.resolveStatus(cur.getRunMode(), cur.getScheduleTime(),
                    AgentWorker.STATUS_RUNNING, true));
        }
        cur.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(cur);
        return ApiResponse.ok(WorkerView.from(cur));
    }

    @PostMapping("/{id}/toggle")
    public ApiResponse<WorkerView> toggle(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "启用或停用数字员工");
        AgentWorker w = requireOwned(user, id);
        boolean next = Integer.valueOf(0).equals(w.getEnabled());
        w.setEnabled(next ? 1 : 0);
        boolean configured = w.getScheduleTime() != null && !w.getScheduleTime().isBlank();
        w.setStatus(!next ? "已停用"
                : (configured ? AgentWorker.STATUS_RUNNING : AgentWorker.STATUS_PENDING_CONFIG));
        w.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(w);
        return ApiResponse.ok(WorkerView.from(w));
    }

    /** 执行记录（真实运行留痕，倒序）。 */
    @GetMapping("/{id}/runs")
    public ApiResponse<List<AgentWorkerRun>> runs(@PathVariable Long id,
                                                  @RequestParam(name = "limit", defaultValue = "20") int limit) {
        AuthUser user = AuthUserContext.require();
        AgentWorker cur = requireOwned(user, id);
        return ApiResponse.ok(runMapper.selectList(new LambdaQueryWrapper<AgentWorkerRun>()
                .eq(AgentWorkerRun::getWorkerId, cur.getId())
                .orderByDesc(AgentWorkerRun::getStartedAt)
                .last("limit " + Math.max(1, Math.min(limit, 100)))));
    }

    /** 立即执行一次（手动触发，真实调模型、落记录、发通知）。 */
    @PostMapping("/{id}/run")
    public ApiResponse<AgentWorkerRun> run(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "手动执行数字员工");
        AgentWorker cur = requireOwned(user, id);
        if (trim(cur.getTaskPrompt()).isEmpty()) {
            throw BizException.badRequest("该数字员工尚未配置任务内容，请先编辑补全后再执行");
        }
        return ApiResponse.ok(scheduleService.runNow(cur, AgentWorkerRun.TRIGGER_MANUAL));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Boolean> delete(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "删除数字员工");
        requireOwned(user, id);
        return ApiResponse.ok(workerMapper.deleteById(id) > 0);
    }

    /**
     * 管理类操作的统一闸门：仅租户管理员。
     *
     * <p>不通过即 403 前置拒绝——不落库、不改状态、不产生半成品。
     * 提示语明确给出「谁能做」与「普通成员能做什么」，便于用户自助判断而不是反复试错。</p>
     */
    private static void requireAdmin(AuthUser user, String action) {
        if (!PermissionCatalog.isAdmin(user)) {
            throw BizException.forbidden(action + "仅租户管理员可执行；"
                    + "如需变更数字员工配置，请联系租户管理员。提交请假申请等业务操作不受此限制。");
        }
    }

    private AgentWorker requireOwned(AuthUser user, Long id) {
        AgentWorker cur = workerMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        return cur;
    }

    /** 角色类型：显式指定优先，未指定则按名称/职责推断（保证历史与「一句话创建」都有类型）。 */
    private static WorkerRole resolveRole(String explicitType, String name, String description) {
        if (explicitType != null && !explicitType.isBlank()) {
            return WorkerRole.of(explicitType);
        }
        return WorkerRole.infer(name, description);
    }

    /**
     * 权限准入：创建或承担某类型数字人角色，必须持有该类型所需权限。
     * 不满足即 403，属**前置拒绝**——不落库、不产生半成品角色。
     */
    private static void requirePermission(AuthUser user, WorkerRole role) {
        String permission = role.requiredPermission();
        if (!PermissionCatalog.holds(user, permission)) {
            throw BizException.forbidden("该数字人属「" + role.displayName() + "」，需持有权限码 " + permission
                    + "（" + PermissionCatalog.rolesText(permission) + "）；当前账号无权创建或承担该类型角色");
        }
    }

    /** 解析执行时刻：支持 HH:mm 与自然语言（每天8点 / 8:30），无法解析返回 null。 */
    private static String resolveScheduleTime(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        // 先按标准格式严格校验（保证前端传错能明确报错而不是静默丢弃）
        try {
            return ScheduleTimeSupport.normalize(raw);
        } catch (BizException e) {
            String flexible = ScheduleTimeSupport.parseFlexible(raw);
            if (flexible == null) {
                throw e;
            }
            return flexible;
        }
    }

    /** 任务内容：为空时用职责描述兜底，保证调度器有内容可执行。 */
    private static String resolveTaskPrompt(String taskPrompt, String description) {
        String p = trim(taskPrompt);
        if (!p.isEmpty()) {
            return p;
        }
        String d = trim(description);
        return d.isEmpty() ? null : d;
    }

    /**
     * 运行模式解析（V22）：显式传入优先；未传时按角色类型推断——请假审批类的本质是
     * 「有申请即审」的事件驱动，其余默认定时型。取值非法即 400，避免静默落到错误模式
     * 导致「待配置」误判（走查发现 D-2）。
     */
    private static String resolveRunMode(String requested, String workerType) {
        if (requested != null && !requested.isBlank()) {
            String v = requested.trim();
            if (AgentWorker.RUN_MODE_SCHEDULED.equalsIgnoreCase(v)
                    || AgentWorker.RUN_MODE_EVENT.equalsIgnoreCase(v)
                    || AgentWorker.RUN_MODE_ON_DEMAND.equalsIgnoreCase(v)) {
                return v.toUpperCase();
            }
            throw BizException.badRequest("运行模式取值非法：" + requested
                    + "（可选 SCHEDULED 定时 / EVENT 事件驱动 / ON_DEMAND 按需唤起）");
        }
        return WorkerRole.of(workerType) == WorkerRole.LEAVE_APPROVER
                ? AgentWorker.RUN_MODE_EVENT
                : AgentWorker.RUN_MODE_SCHEDULED;
    }

    private static String trim(String s) {
        return s == null ? "" : s.trim();
    }
}
