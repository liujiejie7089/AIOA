package cn.aioa.project.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.service.PmDigitalWorkerService;
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
 * 项目数字人分配 + 项目上下文控制接口（PM「数字人」批次，V74 / V76）。
 *
 * <p>设计依据 {@code docs/43 §5}。用户关键词：「分配项目数字人（后台上传，网上搜索,政策）」
 * 「项目上下文控制」。</p>
 *
 * <p>权限一律在 {@link PmDigitalWorkerService} 内判定（{@code requireVisible} + {@code requireWrite}），
 * 控制器不做二次鉴权（两处判定迟早漂移，见 {@code PmDocController} 同款说明）。</p>
 *
 * <p><b>不新建第二套数字人</b>：本控制器只做「把既有数字员工挂到项目」与「维护其上下文来源」；
 * 数字员工本身的增删改仍在「数字员工」域。</p>
 */
@RestController
@RequestMapping("/api/v1/pm")
@RequiredArgsConstructor
public class PmDigitalWorkerController {

    private final OrgGuard guard;
    private final PmDigitalWorkerService service;

    // ======================================================================
    // 数字员工分配
    // ======================================================================

    /** 项目已分配数字员工 + 可分配候选。 */
    @GetMapping("/projects/{id}/workers")
    public ApiResponse<Map<String, Object>> workers(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.workers(u, id));
    }

    /** 分配一个既有数字员工到本项目。{@code body: {workerId, assignRole?}} */
    @PostMapping("/projects/{id}/workers")
    public ApiResponse<Map<String, Object>> assignWorker(@PathVariable Long id,
                                                         @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.assignWorker(u, id, body));
    }

    /** 改用途说明 / 启停。{@code body: {assignRole?, enabled?}} */
    @PutMapping("/projects/{id}/workers/{workerRowId}")
    public ApiResponse<Map<String, Object>> updateWorker(@PathVariable Long id,
                                                         @PathVariable Long workerRowId,
                                                         @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.updateWorker(u, id, workerRowId, body));
    }

    /** 从项目移除数字员工（一并软删其专属上下文来源）。 */
    @DeleteMapping("/projects/{id}/workers/{workerRowId}")
    public ApiResponse<Map<String, Object>> unassignWorker(@PathVariable Long id,
                                                           @PathVariable Long workerRowId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.unassignWorker(u, id, workerRowId));
    }

    // ======================================================================
    // 上下文来源（UPLOAD / WEB_SEARCH / POLICY）
    // ======================================================================

    @GetMapping("/projects/{id}/context-sources")
    public ApiResponse<Map<String, Object>> contextSources(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.contextSources(u, id));
    }

    /** 新增上下文来源。{@code body: {sourceType, name?, workerId?, folderId?, fileId?, kbDocumentId?, config?}} */
    @PostMapping("/projects/{id}/context-sources")
    public ApiResponse<Map<String, Object>> createContextSource(@PathVariable Long id,
                                                                @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.createContextSource(u, id, body));
    }

    @PutMapping("/projects/{id}/context-sources/{sourceId}")
    public ApiResponse<Map<String, Object>> updateContextSource(@PathVariable Long id,
                                                                @PathVariable Long sourceId,
                                                                @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.updateContextSource(u, id, sourceId, body));
    }

    @DeleteMapping("/projects/{id}/context-sources/{sourceId}")
    public ApiResponse<Void> deleteContextSource(@PathVariable Long id, @PathVariable Long sourceId) {
        AuthUser u = guard.requireOrgUser();
        service.deleteContextSource(u, id, sourceId);
        return ApiResponse.ok();
    }

    // ======================================================================
    // 生效视图
    // ======================================================================

    /**
     * 某数字员工在本项目**实际生效**的上下文（项目级默认 + 员工专属，仅 enabled=1）。
     * 省略 {@code workerId} 时只看项目级默认。
     */
    @GetMapping("/projects/{id}/ai-scope")
    public ApiResponse<Map<String, Object>> effectiveScope(@PathVariable Long id,
                                                           @RequestParam(required = false) Long workerId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(service.effectiveScope(u, id, workerId));
    }
}
