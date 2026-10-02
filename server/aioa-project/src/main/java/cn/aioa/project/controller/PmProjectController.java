package cn.aioa.project.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.service.PmProjectMemberService;
import cn.aioa.project.service.PmProjectService;
import cn.aioa.project.support.PmProjectRoles;
import cn.aioa.project.support.PmProjectStatus;
import cn.aioa.project.support.PmProjectType;
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

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 项目管理（PM）接口：项目 / 成员 / 仓库绑定。
 *
 * <p><b>为什么成员与仓库挂在同一个 Controller</b>：契约上它们都属于「一个项目的视图」，
 * 路径以 {@code /projects/{id}/...} 收敛，拆成三个类只会让前端记三套前缀（同 {@code GiteeController} 的取舍）。</p>
 *
 * <p><b>权限一律在服务层判定</b>（{@code requireVisible(forWrite)} + 项目角色），
 * 控制器不做二次鉴权 —— 两处判定迟早漂移，漂移就是越权或功能不可用。</p>
 */
@RestController
@RequestMapping("/api/v1/pm")
@RequiredArgsConstructor
public class PmProjectController {

    private final OrgGuard guard;
    private final PmProjectService projectService;
    private final PmProjectMemberService memberService;

    /** 前端初始化信息：类型/状态/角色枚举都由后端一处给出，前端只渲染。 */
    @GetMapping("/config")
    public ApiResponse<Map<String, Object>> config() {
        guard.requireOrgUser();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("projectTypes", List.of(
                Map.of("value", PmProjectType.BUSINESS, "label", "业务项目",
                        "hint", "只含业务字段，不涉及代码仓库"),
                Map.of("value", PmProjectType.DEV, "label", "开发项目",
                        "hint", "可绑定代码仓库，任务可关联仓库 / issue / 分支 / 提交")));
        m.put("statuses", List.of(
                Map.of("value", PmProjectStatus.DRAFT, "label", "草稿"),
                Map.of("value", PmProjectStatus.ACTIVE, "label", "进行中"),
                Map.of("value", PmProjectStatus.SUSPENDED, "label", "暂停"),
                Map.of("value", PmProjectStatus.CLOSED, "label", "已结项"),
                Map.of("value", PmProjectStatus.ARCHIVED, "label", "已归档")));
        m.put("projectRoleOptions", PmProjectRoles.options());
        return ApiResponse.ok(m);
    }

    // ======================================================================
    // 项目
    // ======================================================================

    @GetMapping("/projects")
    public ApiResponse<List<Map<String, Object>>> list(@RequestParam(required = false) String keyword,
                                                       @RequestParam(required = false) String projectType,
                                                       @RequestParam(required = false) String status,
                                                       @RequestParam(required = false) Long departmentId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.list(u, keyword, projectType, status, departmentId));
    }

    @PostMapping("/projects")
    public ApiResponse<Map<String, Object>> create(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.create(u, body));
    }

    @GetMapping("/projects/{id}")
    public ApiResponse<Map<String, Object>> detail(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.detail(u, id));
    }

    @PutMapping("/projects/{id}")
    public ApiResponse<Map<String, Object>> update(@PathVariable Long id,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.update(u, id, body));
    }

    @PostMapping("/projects/{id}/status")
    public ApiResponse<Map<String, Object>> changeStatus(@PathVariable Long id,
                                                         @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.changeStatus(u, id, PmProjectService.str(body.get("status"))));
    }

    @DeleteMapping("/projects/{id}")
    public ApiResponse<Void> softDelete(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        projectService.softDelete(u, id);
        return ApiResponse.ok();
    }

    // ======================================================================
    // 仓库绑定（仅开发项目）
    // ======================================================================

    @GetMapping("/projects/{id}/repos")
    public ApiResponse<List<Map<String, Object>>> boundRepos(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.boundRepos(u, id));
    }

    @GetMapping("/projects/{id}/repos/bindable")
    public ApiResponse<List<Map<String, Object>>> bindableRepos(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.bindableRepos(u, id));
    }

    /** 新建流程专用：还没有项目 id 时挑可绑仓库（鉴权依据为「有新建项目权限」）。 */
    @GetMapping("/repos/bindable")
    public ApiResponse<List<Map<String, Object>>> bindableReposForCreate() {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.bindableReposForCreate(u));
    }

    @PostMapping("/projects/{id}/repos")
    public ApiResponse<Map<String, Object>> bindRepo(@PathVariable Long id,
                                                     @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.bindRepo(u, id, PmProjectService.asLong(body.get("repoId"))));
    }

    @DeleteMapping("/projects/{id}/repos/{repoId}")
    public ApiResponse<Map<String, Object>> unbindRepo(@PathVariable Long id, @PathVariable Long repoId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(projectService.unbindRepo(u, id, repoId));
    }

    // ======================================================================
    // 成员
    // ======================================================================

    @GetMapping("/projects/{id}/members")
    public ApiResponse<Map<String, Object>> members(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(memberService.list(u, id));
    }

    @GetMapping("/projects/{id}/members/candidates")
    public ApiResponse<List<Map<String, Object>>> memberCandidates(@PathVariable Long id,
                                                                   @RequestParam(required = false) String keyword) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(memberService.candidates(u, id, keyword));
    }

    @PostMapping("/projects/{id}/members")
    public ApiResponse<Map<String, Object>> addMember(@PathVariable Long id,
                                                      @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(memberService.add(u, id,
                PmProjectService.asLong(body.get("memberId")),
                PmProjectService.str(body.get("roleCode"))));
    }

    @PutMapping("/projects/{id}/members/{rowId}")
    public ApiResponse<Map<String, Object>> changeRole(@PathVariable Long id, @PathVariable Long rowId,
                                                       @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(memberService.changeRole(u, id, rowId, PmProjectService.str(body.get("roleCode"))));
    }

    @DeleteMapping("/projects/{id}/members/{rowId}")
    public ApiResponse<Map<String, Object>> removeMember(@PathVariable Long id, @PathVariable Long rowId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(memberService.remove(u, id, rowId));
    }
}
