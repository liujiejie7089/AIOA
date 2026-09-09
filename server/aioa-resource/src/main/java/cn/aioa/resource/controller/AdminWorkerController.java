package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.mapper.AgentWorkerMapper;
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
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 数字员工 —— 管理端维护（V1.2 新增）：
 *   GET/POST/PUT/DELETE /api/v1/admin/workers[/{id}]、POST /{id}/toggle
 * 管理员可预置数字员工并维护运行计划；用户端创建的一并在此可见。
 */
@RestController
@RequestMapping("/api/v1/admin/workers")
@RequiredArgsConstructor
public class AdminWorkerController {

    private final AgentWorkerMapper workerMapper;

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("数字员工维护仅租户管理员可操作");
        }
        return user;
    }

    @GetMapping
    public ApiResponse<List<AgentWorker>> list() {
        AuthUser user = requireAdmin();
        return ApiResponse.ok(workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                .eq(AgentWorker::getTenantId, user.getTenantId())
                .orderByAsc(AgentWorker::getId)));
    }

    @PostMapping
    public ApiResponse<AgentWorker> create(@RequestBody AgentWorker body) {
        AuthUser user = requireAdmin();
        if (body.getName() == null || body.getName().isBlank()) {
            throw BizException.badRequest("数字员工名称不能为空");
        }
        body.setId(null);
        body.setTenantId(user.getTenantId());
        body.setCreatedBy(user.getUserId());
        body.setCreatedAt(LocalDateTime.now());
        body.setUpdatedAt(LocalDateTime.now());
        if (body.getEnabled() == null) body.setEnabled(1);
        if (body.getStatus() == null) body.setStatus(AgentWorker.STATUS_RUNNING);
        if (body.getIcon() == null || body.getIcon().isBlank()) body.setIcon("bot");
        workerMapper.insert(body);
        return ApiResponse.ok(body);
    }

    @PutMapping("/{id}")
    public ApiResponse<AgentWorker> update(@PathVariable Long id, @RequestBody AgentWorker body) {
        AuthUser user = requireAdmin();
        AgentWorker cur = workerMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        body.setId(id);
        body.setTenantId(cur.getTenantId());
        body.setCreatedBy(cur.getCreatedBy());
        body.setCreatedAt(cur.getCreatedAt());
        body.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(body);
        return ApiResponse.ok(body);
    }

    @PostMapping("/{id}/toggle")
    public ApiResponse<AgentWorker> toggle(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        AgentWorker cur = workerMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        boolean next = Integer.valueOf(0).equals(cur.getEnabled());
        cur.setEnabled(next ? 1 : 0);
        cur.setStatus(next ? AgentWorker.STATUS_RUNNING : AgentWorker.STATUS_IDLE);
        cur.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(cur);
        return ApiResponse.ok(cur);
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Boolean> delete(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        AgentWorker cur = workerMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("数字员工不存在：" + id);
        }
        return ApiResponse.ok(workerMapper.deleteById(id) > 0);
    }
}
