package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.AgentWorkerRun;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AgentWorkerRunMapper;
import cn.aioa.resource.service.WorkerScheduleService;
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
 */
@RestController
@RequestMapping("/api/v1/workers")
@RequiredArgsConstructor
public class WorkerController {

    private final AgentWorkerMapper workerMapper;
    private final AgentWorkerRunMapper runMapper;
    private final WorkerScheduleService scheduleService;

    public record WorkerView(Long id, String name, String icon, String description, String status,
                             String lastOutput, String schedule, String scheduleTime, String taskPrompt,
                             String lastRunAt, boolean on) {

        static WorkerView from(AgentWorker w) {
            boolean on = !Integer.valueOf(0).equals(w.getEnabled());
            String status = on
                    ? (w.getScheduleTime() == null || w.getScheduleTime().isBlank()
                    ? AgentWorker.STATUS_PENDING_CONFIG : w.getStatus())
                    : "已停用";
            return new WorkerView(w.getId(), w.getName(), w.getIcon(), w.getDescription(), status,
                    w.getLastOutput(), w.getScheduleText(), w.getScheduleTime(), w.getTaskPrompt(),
                    w.getLastRunAt() == null ? null : w.getLastRunAt().toString(), on);
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

    @PostMapping
    public ApiResponse<WorkerView> create(@RequestBody AgentWorker body) {
        AuthUser user = AuthUserContext.require();
        String name = trim(body.getName());
        if (name.isEmpty()) {
            throw BizException.badRequest("数字员工名称不能为空");
        }
        AgentWorker w = new AgentWorker();
        w.setTenantId(user.getTenantId());
        w.setName(name);
        w.setIcon(trim(body.getIcon()).isEmpty() ? "bot" : body.getIcon());
        w.setDescription(body.getDescription());
        w.setEnabled(1);

        // 关键：执行时刻与任务内容必须落库，否则定时调度永远不匹配
        String scheduleTime = resolveScheduleTime(body.getScheduleTime());
        String taskPrompt = resolveTaskPrompt(body.getTaskPrompt(), body.getDescription());
        w.setScheduleTime(scheduleTime);
        w.setTaskPrompt(taskPrompt);
        w.setScheduleText(trim(body.getScheduleText()).isEmpty()
                ? (scheduleTime == null ? "按计划执行" : "每天 " + scheduleTime + " 自动执行")
                : body.getScheduleText());
        w.setStatus(scheduleTime == null ? AgentWorker.STATUS_PENDING_CONFIG : AgentWorker.STATUS_RUNNING);
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
        if (body.getDescription() != null) {
            cur.setDescription(body.getDescription());
        }
        if (body.getScheduleText() != null) {
            cur.setScheduleText(body.getScheduleText());
        }
        // 执行时刻：显式传 null/空串表示清空（回到「待配置」）
        if (body.getScheduleTime() != null) {
            cur.setScheduleTime(resolveScheduleTime(body.getScheduleTime()));
        }
        if (body.getTaskPrompt() != null) {
            cur.setTaskPrompt(resolveTaskPrompt(body.getTaskPrompt(), cur.getDescription()));
        }
        // 状态：启用中按是否配置了执行时刻自动重算；停用保持停用
        if (!Integer.valueOf(0).equals(cur.getEnabled())) {
            cur.setStatus(cur.getScheduleTime() == null || cur.getScheduleTime().isBlank()
                    ? AgentWorker.STATUS_PENDING_CONFIG : AgentWorker.STATUS_RUNNING);
        }
        cur.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(cur);
        return ApiResponse.ok(WorkerView.from(cur));
    }

    @PostMapping("/{id}/toggle")
    public ApiResponse<WorkerView> toggle(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
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
        AgentWorker cur = requireOwned(user, id);
        if (trim(cur.getTaskPrompt()).isEmpty()) {
            throw BizException.badRequest("该数字员工尚未配置任务内容，请先编辑补全后再执行");
        }
        return ApiResponse.ok(scheduleService.runNow(cur, AgentWorkerRun.TRIGGER_MANUAL));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Boolean> delete(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        requireOwned(user, id);
        return ApiResponse.ok(workerMapper.deleteById(id) > 0);
    }

    private AgentWorker requireOwned(AuthUser user, Long id) {
        AgentWorker cur = workerMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        return cur;
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

    private static String trim(String s) {
        return s == null ? "" : s.trim();
    }
}
