package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 数字员工（V1.2 新增）：自动运行 · 定时产出 · 结果进入待办与消息。
 *   GET  /api/v1/workers              —— 本租户数字员工列表
 *   POST /api/v1/workers              —— 创建（会话内「一句话创建」确认后调用）
 *   POST /api/v1/workers/{id}/toggle  —— 启用 / 停用（历史产出保留）
 */
@RestController
@RequestMapping("/api/v1/workers")
@RequiredArgsConstructor
public class WorkerController {

    private final AgentWorkerMapper workerMapper;

    public record WorkerView(Long id, String name, String icon, String description, String status,
                             String lastOutput, String schedule, boolean on) {

        static WorkerView from(AgentWorker w) {
            boolean on = !Integer.valueOf(0).equals(w.getEnabled());
            return new WorkerView(w.getId(), w.getName(), w.getIcon(), w.getDescription(),
                    on ? w.getStatus() : "已停用",
                    w.getLastOutput(), w.getScheduleText(), on);
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
        w.setStatus(AgentWorker.STATUS_RUNNING);
        w.setLastOutput("尚未运行");
        w.setScheduleText(trim(body.getScheduleText()).isEmpty() ? "按计划执行" : body.getScheduleText());
        w.setEnabled(1);
        w.setCreatedBy(user.getUserId());
        w.setCreatedAt(LocalDateTime.now());
        w.setUpdatedAt(LocalDateTime.now());
        workerMapper.insert(w);
        return ApiResponse.ok(WorkerView.from(w));
    }

    @PostMapping("/{id}/toggle")
    public ApiResponse<WorkerView> toggle(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        AgentWorker w = workerMapper.selectById(id);
        if (w == null || !user.getTenantId().equals(w.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        boolean next = Integer.valueOf(0).equals(w.getEnabled());
        w.setEnabled(next ? 1 : 0);
        w.setStatus(next ? AgentWorker.STATUS_RUNNING : AgentWorker.STATUS_IDLE);
        w.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(w);
        return ApiResponse.ok(WorkerView.from(w));
    }

    private static String trim(String s) {
        return s == null ? "" : s.trim();
    }
}
