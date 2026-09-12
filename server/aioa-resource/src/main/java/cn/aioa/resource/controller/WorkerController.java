package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.AgentWorkerRun;
import cn.aioa.resource.entity.ClientActivityLog;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AgentWorkerRunMapper;
import cn.aioa.resource.mapper.ClientActivityLogMapper;
import cn.aioa.resource.service.ContentReviewService;
import cn.aioa.resource.service.WorkerScheduleService;
import cn.aioa.resource.support.PermissionCatalog;
import cn.aioa.resource.support.ScheduleTimeSupport;
import cn.aioa.resource.support.WorkerRole;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

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
    private final ClientActivityLogMapper activityLogMapper;
    /** 审计快照序列化（Spring Boot 自带实例）。 */
    private final ObjectMapper objectMapper;
    private final ContentReviewService reviewService;

    /**
     * 数字员工变更留痕：谁、何时、对哪个数字员工、做了什么、<b>改前改后各是什么</b>。
     *
     * <p>写入本模块既有的活动日志（管理端「系统管理 → 审计」直接可见），
     * 不写 audit_log——那张表带 hash 链，跨模块直接插会破坏链校验。</p>
     *
     * <p>V32 补齐 V1.2 遗留短板：此前只记动作、不记变更值，无法回答
     * 「改之前是什么、改之后是什么」，不满足审计可追溯要求。</p>
     */
    private void audit(AuthUser user, String action, String label, Object before, Object after) {
        try {
            ClientActivityLog log = new ClientActivityLog();
            log.setTenantId(user.getTenantId());
            log.setUserId(user.getUserId());
            log.setAction(action);
            log.setStatus("SUCCESS");
            log.setLabel(label);
            log.setBeforeValue(json(before));
            log.setAfterValue(json(after));
            log.setCreatedBy(user.getUserId());
            log.setCreatedAt(LocalDateTime.now());
            log.setUpdatedAt(LocalDateTime.now());
            activityLogMapper.insert(log);
        } catch (Exception ignored) {
            // 审计失败不应阻断业务：留痕是增强，不是主流程
        }
    }

    private String json(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 数字员工的可审计快照：只取<b>配置类</b>字段。
     *
     * <p>刻意不含 {@code lastOutput} 等运行产出，避免审计表被大文本撑爆。
     * 返回新 Map（值已拷贝），故在变更<b>前</b>调用即可安全留存旧值。</p>
     */
    private static Map<String, Object> snapshot(AgentWorker w) {
        if (w == null) {
            return null;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", w.getId());
        m.put("name", w.getName());
        m.put("workerType", w.getWorkerType());
        m.put("runMode", w.getRunMode());
        m.put("scheduleTime", w.getScheduleTime());
        m.put("taskPrompt", w.getTaskPrompt());
        m.put("status", w.getStatus());
        m.put("enabled", w.getEnabled());
        m.put("visibleScope", w.getVisibleScope());
        m.put("deptIds", w.getDeptIds());
        m.put("institutionId", w.getInstitutionId());
        return m;
    }

    public record WorkerView(Long id, String name, String icon, String description, String status,
                             String lastOutput, String schedule, String scheduleTime, String runMode,
                             String taskPrompt,
                             String lastRunAt, boolean on,
                             String workerType, String roleName, String duty, String requiredPermission,
                             String visibleScope, String deptIds, Long sourceTemplateId,
                             Long createdBy, boolean mine, boolean editable,
                             String auditStatus, String auditNote) {

        static WorkerView from(AgentWorker w) {
            return from(w, null);
        }

        /**
         * @param viewer 当前查看者；传入时用于计算 {@code mine}/{@code editable}，
         *               前端据此决定是否展示「调整任务 / 启停」等管理入口（后端仍会二次校验）。
         */
        static WorkerView from(AgentWorker w, AuthUser viewer) {
            boolean on = !Integer.valueOf(0).equals(w.getEnabled());
            // V22：只有定时型（SCHEDULED）缺执行时刻才判「待配置」；
            // 事件驱动（EVENT）/按需唤起（ON_DEMAND）不需要执行时刻，不再被误标。
            String status = AgentWorker.resolveStatus(w.getRunMode(), w.getScheduleTime(), w.getStatus(), on);
            WorkerRole role = WorkerRole.of(w.getWorkerType());
            boolean mine = PermissionCatalog.isCreator(viewer, w.getCreatedBy());
            boolean editable = viewer != null
                    && (PermissionCatalog.holds(viewer, PermissionCatalog.WORKER_MANAGE) || mine);
            return new WorkerView(w.getId(), w.getName(), w.getIcon(), w.getDescription(), status,
                    w.getLastOutput(), w.getScheduleText(), w.getScheduleTime(), w.getRunMode(), w.getTaskPrompt(),
                    w.getLastRunAt() == null ? null : w.getLastRunAt().toString(), on,
                    role.code(), role.displayName(), role.duty(), role.requiredPermission(),
                    w.getVisibleScope(), w.getDeptIds(), w.getSourceTemplateId(),
                    w.getCreatedBy(), mine, editable, w.getAuditStatus(), w.getAuditNote());
        }
    }

    /** 全局模板视图：供租户「从模板创建」，只读。 */
    public record TemplateView(Long id, String name, String icon, String description,
                               String workerType, String roleName, String runMode, String taskPrompt) {

        static TemplateView from(AgentWorker w) {
            WorkerRole role = WorkerRole.of(w.getWorkerType());
            return new TemplateView(w.getId(), w.getName(), w.getIcon(), w.getDescription(),
                    role.code(), role.displayName(), w.getRunMode(), w.getTaskPrompt());
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
            boolean canCreate = PermissionCatalog.holds(user, PermissionCatalog.WORKER_CREATE)
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
                .stream()
                .filter(w -> visibleTo(w, user))
                // V34：待审内容不对普通成员可见（创建者本人与管理员例外，见 ContentReviewService#visible）
                .filter(w -> reviewService.visible(w.getAuditStatus(), user, w.getCreatedBy()))
                .map(w -> WorkerView.from(w, user)).toList());
    }

    /**
     * 全局模板列表（tenant_id=0 且 is_template=1），供租户「从模板创建」。
     * 只读，任何登录用户可见——模板是平台公共资产，不含租户数据。
     */
    @GetMapping("/templates")
    public ApiResponse<List<TemplateView>> templates() {
        AuthUserContext.require();
        return ApiResponse.ok(workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                        .eq(AgentWorker::getTenantId, 0L)
                        .eq(AgentWorker::getIsTemplate, 1)
                        .orderByAsc(AgentWorker::getId))
                .stream().map(TemplateView::from).toList());
    }

    /**
     * 从全局模板复制到本租户，解决「租户开通后数字员工列表为空」。
     *
     * <p>仅复制可复制的样板字段（名称/职责/运行模式/任务内容），
     * 不复制 tenant_id、状态与执行记录——模板是样板，不是运行实例。</p>
     */
    @PostMapping("/from-template/{templateId}")
    public ApiResponse<WorkerView> fromTemplate(@PathVariable Long templateId,
                                                @RequestBody(required = false) java.util.Map<String, Object> body) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "从模板创建数字员工");
        AgentWorker tpl = workerMapper.selectById(templateId);
        if (tpl == null || !Long.valueOf(0L).equals(tpl.getTenantId()) || !Integer.valueOf(1).equals(tpl.getIsTemplate())) {
            throw BizException.notFound("模板不存在：" + templateId);
        }
        AgentWorker w = new AgentWorker();
        w.setTenantId(user.getTenantId());
        w.setInstitutionId(user.getInstitutionId());
        String name = body == null ? null : trim((String) body.get("name"));
        w.setName(name == null || name.isEmpty() ? tpl.getName() : name);
        w.setIcon(tpl.getIcon());
        w.setDescription(tpl.getDescription());
        w.setWorkerType(tpl.getWorkerType());
        w.setRunMode(tpl.getRunMode() == null ? AgentWorker.RUN_MODE_ON_DEMAND : tpl.getRunMode());
        w.setScheduleText(tpl.getScheduleText());
        w.setScheduleTime(tpl.getScheduleTime());
        w.setTaskPrompt(tpl.getTaskPrompt());
        w.setStatus(AgentWorker.STATUS_IDLE);
        w.setEnabled(1);
        w.setCreatedBy(user.getUserId());
        w.setVisibleScope("TENANT");
        w.setSourceTemplateId(tpl.getId());
        w.setIsTemplate(0);
        // V34：与直接创建同一口径——租户管理员「从模板创建」同样是新内容，同样需上级审核，
        // 否则这里会成为绕开审核的旁路。
        w.setAuditStatus(reviewService.initialStatus(user));
        // 模板类型可能要求特定权限码（如请假类需 approval:leave）
        requirePermission(user, WorkerRole.of(tpl.getWorkerType()));
        workerMapper.insert(w);
        audit(user, "worker.from_template", "从模板「" + tpl.getName() + "」(id=" + templateId + ") 创建数字员工",
                null, snapshot(w));
        return ApiResponse.ok(WorkerView.from(w, user));
    }

    /**
     * 设置可见范围（部门分发）：body = {scope:"TENANT"|"DEPT", deptIds:[1,2]}。
     *
     * <p>仅租户管理员可操作——把数字员工分发到哪些部门，属于租户内的管控动作。</p>
     */
    @PutMapping("/{id}/visible-scope")
    public ApiResponse<WorkerView> setVisibleScope(@PathVariable Long id,
                                                   @RequestBody java.util.Map<String, Object> body) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "设置数字员工可见范围");
        AgentWorker w = requireOwned(user, id);
        Map<String, Object> beforeScope = snapshot(w);
        String scope = body == null ? null : (String) body.get("scope");
        if (scope == null || scope.isBlank()) {
            scope = "TENANT";
        }
        scope = scope.trim().toUpperCase();
        if (!"TENANT".equals(scope) && !"DEPT".equals(scope)) {
            throw BizException.badRequest("可见范围只能为 TENANT 或 DEPT");
        }
        // 部门负责人：只能把员工锁定在本部门，不得改成全租户可见（否则等于自我提权）
        if (PermissionCatalog.isDeptLeaderOnly(user)) {
            Long deptId = user.getDepartmentId();
            if (deptId == null) {
                throw BizException.forbidden("您的账号未绑定部门，无法设置可见范围");
            }
            w.setVisibleScope("DEPT");
            w.setDeptIds("[" + deptId + "]");
        } else {
            w.setVisibleScope(scope);
            if ("DEPT".equals(scope)) {
                Object ids = body.get("deptIds");
                if (ids == null || !(ids instanceof java.util.List<?> list) || list.isEmpty()) {
                    throw BizException.badRequest("scope=DEPT 时必须指定 deptIds");
                }
                w.setDeptIds(list.toString());
            } else {
                w.setDeptIds(null);
            }
        }
        workerMapper.updateById(w);
        audit(user, "worker.scope", "设置数字员工「" + w.getName() + "」(id=" + id + ") 可见范围="
                + w.getVisibleScope() + (w.getDeptIds() == null ? "" : " 部门=" + w.getDeptIds()),
                beforeScope, snapshot(w));
        return ApiResponse.ok(WorkerView.from(w, user));
    }

    /**
     * 可见性判定：角色决定「能做什么」，本方法决定「能看到哪个数字员工」。
     *
     * <p>管理员可见全部——否则租户管理员将无法管理自己下发到部门的数字员工。</p>
     */
    private static boolean visibleTo(AgentWorker w, AuthUser user) {
        if (PermissionCatalog.isAdmin(user)) {
            return true;
        }
        String scope = w.getVisibleScope();
        if (scope == null || scope.isBlank() || "TENANT".equals(scope)) {
            return true;
        }
        // V33：SELF = 创建者私有。普通成员自建的数字员工不该出现在他人列表里，
        // 否则「人人可建」会变成互相可见的噪音。
        if ("SELF".equals(scope)) {
            return PermissionCatalog.isCreator(user, w.getCreatedBy());
        }
        if (!"DEPT".equals(scope)) {
            return false;
        }
        Long deptId = user.getDepartmentId();
        String ids = w.getDeptIds();
        if (deptId == null || ids == null || ids.isBlank()) {
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
        requireCreate(user, "创建数字员工");
        String name = trim(body.getName());
        if (name.isEmpty()) {
            throw BizException.badRequest("数字员工名称不能为空");
        }
        // 角色类型 → 所需权限 → 角色，三者任一处不满足即拒绝创建（V21 权限准入）
        WorkerRole role = resolveRole(body.getWorkerType(), name, body.getDescription());
        requirePermission(user, role);
        AgentWorker w = new AgentWorker();
        w.setTenantId(user.getTenantId());
        // V31：记录归属机构。租户管理员（无机构）创建的是租户级，全租户共享；
        // 企业管理员创建的归本机构，仅本机构可管理。
        w.setInstitutionId(user.getInstitutionId());
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
        // V34：租户管理员创建的内容需平台管理员审核后才生效（开关见 sys_config approval.tenant.content）
        w.setAuditStatus(reviewService.initialStatus(user));
        // 可见范围：默认本租户全员可见；前端可传 DEPT + deptIds 直接分发到部门。
        // 部门负责人不论传什么，一律锁定到本部门（范围纪律，见 V32）。
        applyVisibilityScope(w, user, body);
        w.setIsTemplate(0);
        w.setCreatedAt(LocalDateTime.now());
        w.setUpdatedAt(LocalDateTime.now());
        workerMapper.insert(w);
        audit(user, "worker.create", "创建数字员工「" + w.getName() + "」类型=" + role.code()
                + " 可见范围=" + w.getVisibleScope(), null, snapshot(w));
        return ApiResponse.ok(WorkerView.from(w, user));
    }

    /** 原地更新：只覆盖本次传入的字段，未传的保持原值（避免编辑丢配置）。 */
    @PutMapping("/{id}")
    public ApiResponse<WorkerView> update(@PathVariable Long id, @RequestBody AgentWorker body) {
        AuthUser user = AuthUserContext.require();
        AgentWorker cur = requireOwned(user, id);
        // V33：管理者改全部，普通成员改自己创建的。取到实体后再判，因为要看 created_by。
        requireManageOrOwner(user, cur, "修改数字员工");
        // 变更前快照：cur 会被原地改写，故必须先留底
        Map<String, Object> beforeUpdate = snapshot(cur);

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
        audit(user, "worker.update", "修改数字员工「" + cur.getName() + "」(id=" + id + ")",
                beforeUpdate, snapshot(cur));
        return ApiResponse.ok(WorkerView.from(cur, user));
    }

    @PostMapping("/{id}/toggle")
    public ApiResponse<WorkerView> toggle(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        AgentWorker w = requireOwned(user, id);
        requireManageOrOwner(user, w, "启用或停用数字员工");
        Map<String, Object> before = snapshot(w);
        boolean next = Integer.valueOf(0).equals(w.getEnabled());
        w.setEnabled(next ? 1 : 0);
        boolean configured = w.getScheduleTime() != null && !w.getScheduleTime().isBlank();
        w.setStatus(!next ? "已停用"
                : (configured ? AgentWorker.STATUS_RUNNING : AgentWorker.STATUS_PENDING_CONFIG));
        w.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(w);
        audit(user, "worker.toggle", (next ? "启用" : "停用") + "数字员工「" + w.getName() + "」(id=" + id + ")",
                before, snapshot(w));
        return ApiResponse.ok(WorkerView.from(w, user));
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
        AgentWorkerRun run = scheduleService.runNow(cur, AgentWorkerRun.TRIGGER_MANUAL);
        audit(user, "worker.run", "手动执行数字员工「" + cur.getName() + "」(id=" + id + ")", null,
                Map.of("runId", run.getId() == null ? 0L : run.getId(),
                        "trigger", AgentWorkerRun.TRIGGER_MANUAL,
                        "workerId", cur.getId() == null ? 0L : cur.getId()));
        return ApiResponse.ok(run);
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Boolean> delete(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        requireAdmin(user, "删除数字员工");
        AgentWorker w = requireOwned(user, id);
        Map<String, Object> before = snapshot(w);
        boolean ok = workerMapper.deleteById(id) > 0;
        audit(user, "worker.delete", "删除数字员工「" + w.getName() + "」(id=" + id + ")",
                before, Map.of("id", id, "deleted", ok));
        return ApiResponse.ok(ok);
    }

    /**
     * 管理类操作的统一闸门：仅租户管理员。
     *
     * <p>不通过即 403 前置拒绝——不落库、不改状态、不产生半成品。
     * 提示语明确给出「谁能做」与「普通成员能做什么」，便于用户自助判断而不是反复试错。</p>
     */
    private static void requireAdmin(AuthUser user, String action) {
        if (!PermissionCatalog.holds(user, PermissionCatalog.WORKER_MANAGE)) {
            throw BizException.forbidden(action + "需要管理权限（" + PermissionCatalog.rolesText(PermissionCatalog.WORKER_MANAGE)
                    + "）；当前账号角色为「" + roleText(user) + "」。"
                    + "如需变更数字员工配置，请联系本租户管理员。使用数字员工与提交业务申请不受此限制。");
        }
    }

    /**
     * 修改类操作的闸门：管理者管全部，普通成员只改自己创建的（V33）。
     *
     * <p>先取实体再判定，是因为「是否创建者」必须看数据，不能只看角色。
     * 删除不在此列——删除是不可逆操作，仍只认 {@link PermissionCatalog#WORKER_MANAGE}，
     * 避免「能建就能删」把治理权彻底下放。</p>
     */
    private static void requireManageOrOwner(AuthUser user, AgentWorker w, String action) {
        if (PermissionCatalog.holds(user, PermissionCatalog.WORKER_MANAGE)) {
            return;
        }
        if (PermissionCatalog.holds(user, PermissionCatalog.WORKER_EDIT_SELF)
                && PermissionCatalog.isCreator(user, w.getCreatedBy())) {
            return;
        }
        throw BizException.forbidden(action + "需要管理权限（" + PermissionCatalog.rolesText(PermissionCatalog.WORKER_MANAGE)
                + "）或为本人创建；当前账号角色为「" + roleText(user) + "」。"
                + "自己创建的数字员工可直接修改，他人创建的请联系管理员。");
    }

    /** 创建单独走 worker:create，与「管理」区分——便于将来只下放使用权、不给创建权。 */
    private static void requireCreate(AuthUser user, String action) {
        if (!PermissionCatalog.holds(user, PermissionCatalog.WORKER_CREATE)) {
            throw BizException.forbidden(action + "需要创建权限（" + PermissionCatalog.rolesText(PermissionCatalog.WORKER_CREATE)
                    + "）；当前账号角色为「" + roleText(user) + "」。"
                    + "如需新建数字员工，请联系本租户管理员。");
        }
    }

    /** 当前用户角色的中文描述，用于权限不足时给出可操作的提示。 */
    private static String roleText(AuthUser user) {
        if (user.getRoles() == null || user.getRoles().isEmpty()) {
            return "无角色";
        }
        return String.join("、", user.getRoles());
    }

    private AgentWorker requireOwned(AuthUser user, Long id) {
        AgentWorker cur = workerMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        if (PermissionCatalog.isAdmin(user)) {
            return cur;   // 系统管理员 / 租户管理员：本租户全部
        }
        // V33：创建者恒可访问自己创建的数字员工（含普通成员自建的 SELF 助理）。
        // 放在机构/部门约束之前，因为「自己建的」是比「分给我的」更强的归属关系。
        if (PermissionCatalog.isCreator(user, cur.getCreatedBy())) {
            return cur;
        }
        // V31 机构约束：机构级数字员工（institutionId 非空）只认本机构；租户级（空）不受限。
        if (user.getInstitutionId() != null && cur.getInstitutionId() != null
                && !user.getInstitutionId().equals(cur.getInstitutionId())) {
            throw BizException.forbidden("只能管理本机构的数字员工；该数字员工属于其他机构");
        }
        // V32 部门约束：部门负责人只能管理「已分发到本部门」的数字员工
        if (PermissionCatalog.isDeptLeaderOnly(user) && !deptScopedTo(cur, user.getDepartmentId())) {
            throw BizException.forbidden("部门负责人只能管理已分发到本部门的数字员工；"
                    + "该数字员工不在您本部门（" + user.getDepartmentId() + "）的可见范围内");
        }
        return cur;
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

    /**
     * 可见范围落库规则（V32）。
     *
     * <p>部门负责人是「委派型管理者」：其创建的数字员工<b>强制</b>锁定到本部门，
     * 不接收前端传入的 scope，避免通过改包把员工提升为全租户可见。
     * 机构管理员 / 租户管理员按入参落库（默认 TENANT）。</p>
     */
    private static void applyVisibilityScope(AgentWorker w, AuthUser user, AgentWorker body) {
        // V33：普通成员（非管理者）创建的数字员工一律锁定为 SELF（仅本人可见）。
        // 与其靠校验拦截「越权分发」，不如在源头就不接收 scope 入参——
        // 这样即使前端改包塞 visibleScope=TENANT 也无法把个人助理提升为全员可见。
        if (!PermissionCatalog.isWorkerManager(user)) {
            w.setVisibleScope("SELF");
            w.setDeptIds(null);
            return;
        }
        if (PermissionCatalog.isDeptLeaderOnly(user)) {
            Long deptId = user.getDepartmentId();
            if (deptId == null) {
                throw BizException.forbidden("您的账号未绑定部门，无法创建数字员工；"
                        + "请联系企业管理员将您设置为部门负责人");
            }
            w.setVisibleScope("DEPT");
            w.setDeptIds("[" + deptId + "]");
            return;
        }
        String scope = body.getVisibleScope() == null || body.getVisibleScope().isBlank()
                ? "TENANT" : body.getVisibleScope().trim().toUpperCase();
        w.setVisibleScope("DEPT".equals(scope) ? "DEPT" : "TENANT");
        w.setDeptIds("DEPT".equals(w.getVisibleScope()) ? body.getDeptIds() : null);
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
