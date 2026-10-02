package cn.aioa.project.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.service.PmProjectService;
import cn.aioa.project.service.PmTaskService;
import cn.aioa.security.AuthUser;
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

import java.util.Map;

/**
 * 项目任务接口（业务任务；**非** gitee_task 异步队列）。
 *
 * <p>路径前缀 {@code /api/v1/pm/projects/{id}/tasks}，与项目详情页「任务」页签一一对应。</p>
 */
@RestController
@RequestMapping("/api/v1/pm")
@RequiredArgsConstructor
public class PmTaskController {

    private final OrgGuard guard;
    private final PmTaskService taskService;

    @GetMapping("/projects/{id}/tasks")
    public ApiResponse<Map<String, Object>> list(@PathVariable Long id,
                                                 @RequestParam(required = false) String status,
                                                 @RequestParam(required = false) Long assigneeMemberId,
                                                 @RequestParam(required = false) String keyword) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(taskService.list(u, id, status, assigneeMemberId, keyword));
    }

    @PostMapping("/projects/{id}/tasks")
    public ApiResponse<Map<String, Object>> create(@PathVariable Long id,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(taskService.create(u, id, body));
    }

    @PutMapping("/projects/{id}/tasks/{taskId}")
    public ApiResponse<Map<String, Object>> update(@PathVariable Long id, @PathVariable Long taskId,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(taskService.update(u, id, taskId, body));
    }

    /** 改状态（状态机白名单）。 */
    @PostMapping("/projects/{id}/tasks/{taskId}/status")
    public ApiResponse<Map<String, Object>> transition(@PathVariable Long id, @PathVariable Long taskId,
                                                       @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(taskService.transition(u, id, taskId, PmProjectService.str(body.get("status"))));
    }

    @DeleteMapping("/projects/{id}/tasks/{taskId}")
    public ApiResponse<Void> delete(@PathVariable Long id, @PathVariable Long taskId) {
        AuthUser u = guard.requireOrgUser();
        taskService.delete(u, id, taskId);
        return ApiResponse.ok();
    }
}
