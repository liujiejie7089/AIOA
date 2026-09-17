package cn.aioa.gitee.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.gitee.config.GiteeProperties;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.service.GiteeContentService;
import cn.aioa.gitee.service.GiteeMemberService;
import cn.aioa.gitee.service.GiteeProjectService;
import cn.aioa.gitee.service.GiteeSyncScheduler;
import cn.aioa.gitee.service.GiteeTenantConfigService;
import cn.aioa.gitee.service.GiteeTenantInitService;
import cn.aioa.gitee.service.GiteeTaskService;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Gitee 项目仓库联动接口。
 *
 * <p><b>为什么成员与内容接口挂在同一个 Controller</b>：合同上它们都属于「一个项目的
 * 仓库视图」，拆成三个类只会让前端记住三套前缀；路径以 {@code /projects/{id}/...} 收敛。</p>
 *
 * <p><b>权限</b>：全部由服务层判定（{@code requireVisible(forWrite)} + 权限码），
 * 控制器不做二次鉴权 —— 两处判定迟早会漂移，漂移就是越权或功能不可用。</p>
 */
@RestController
@RequestMapping("/api/v1/gitee")
@RequiredArgsConstructor
public class GiteeController {

    private final OrgGuard guard;
    private final GiteeProperties props;
    private final GiteeTenantConfigService tenantConfigService;
    private final GiteeTenantInitService tenantInitService;
    private final GiteeProjectService projectService;
    private final GiteeMemberService memberService;
    private final GiteeContentService contentService;
    private final GiteeSyncScheduler syncScheduler;
    private final GiteeTaskService taskService;

    // ======================================================================
    // 元信息
    // ======================================================================

    /**
     * 前端初始化信息：决定「仓库联动」菜单是否显示、按钮是否可用。
     *
     * <p>只回布尔与枚举，不回组织名 / 回调地址等内部配置（那些属于部署信息）。</p>
     */
    @GetMapping("/config")
    public ApiResponse<Map<String, Object>> config() {
        AuthUser u = guard.requireOrgUser();
        // 租户级视角的初始化信息：orgConfigured 与 enabled 都按「当前用户所属租户」判定，
        // 而非全局 props（全局值只能作为回落默认值，不能决定单个租户是否可用）。
        Long tenantId = guard.tenantId();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("enabled", props.isEnabled() && tenantConfigService.tenantEnabled(tenantId));
        m.put("orgConfigured", tenantConfigService.orgConfigured(tenantId));
        m.put("webhookBaseUrlConfigured",
                props.getWebhookBaseUrl() != null && !props.getWebhookBaseUrl().isBlank());
        m.put("syncEnabled", props.isSyncEnabled());
        m.put("purgeRepoOnDelete", props.isPurgeRepoOnDelete());
        m.put("roleOptions", List.of(
                Map.of("value", "READ", "label", "只读（可克隆、可读代码）"),
                Map.of("value", "WRITE", "label", "开发者（可推送）"),
                Map.of("value", "ADMIN", "label", "管理员（可改设置）")));
        return ApiResponse.ok(m);
    }

    // ======================================================================
    // 每租户 Gitee 组织配置（多企业各自独立 Gitee 组织）
    // ======================================================================

    /**
     * 查看当前（或指定）租户的 Gitee 组织配置视图。
     *
     * <p>租户管理员只看本租户；平台管理员可经 {@code ?tenantId=} 指定其他租户
     * （沿用 /calibrate 的作用域范式）。租户管理员跨租户会被 {@code resolveScopeTenant} 拒绝（404）。</p>
     */
    @GetMapping("/tenant-config")
    public ApiResponse<Map<String, Object>> tenantConfig(@RequestParam(required = false) Long tenantId) {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = guard.resolveScopeTenant(u, tenantId);
        return ApiResponse.ok(tenantConfigService.view(scope));
    }

    /**
     * 保存（upsert）当前（或指定）租户的 Gitee 组织配置。
     *
     * <p>body：{@code {orgName, enabled?}}。orgName 经保守正则强校验（防路径注入）。
     * 保存后做一次 best-effort 可见性探测（不阻塞保存）。</p>
     */
    @PostMapping("/tenant-config")
    public ApiResponse<Map<String, Object>> saveTenantConfig(@RequestParam(required = false) Long tenantId,
                                                              @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = guard.resolveScopeTenant(u, tenantId);
        String orgName = str(body == null ? null : body.get("orgName"));
        Boolean enabled = bool(body == null ? null : body.get("enabled"));
        return ApiResponse.ok(tenantConfigService.save(scope, orgName, enabled, u.getUserId()));
    }

    /**
     * 清除当前（或指定）租户的组织配置（回落平台全局默认）。
     */
    @DeleteMapping("/tenant-config")
    public ApiResponse<Map<String, Object>> clearTenantConfig(@RequestParam(required = false) Long tenantId) {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = guard.resolveScopeTenant(u, tenantId);
        return ApiResponse.ok(tenantConfigService.clear(scope));
    }

    // ======================================================================
    // 企业主动发起 Gitee 初始化（组织级企业令牌）
    // ======================================================================

    /**
     * 初始化状态视图（不触发任何网络校验）。
     *
     * <p>沿用 /tenant-config 的作用域范式：租户管理员只看本租户；平台管理员可经
     * {@code ?tenantId=} 指定其他租户；租户管理员跨租户被 {@code resolveScopeTenant} 拒绝。</p>
     */
    @GetMapping("/init")
    public ApiResponse<Map<String, Object>> initStatus(@RequestParam(required = false) Long tenantId) {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = guard.resolveScopeTenant(u, tenantId);
        return ApiResponse.ok(tenantInitService.status(u, scope));
    }

    /**
     * 仅校验不落库：{@code {accessToken?, orgName}}。跑到步骤 6 为止，永不写库。
     */
    @PostMapping("/init/verify")
    public ApiResponse<Map<String, Object>> initVerify(@RequestParam(required = false) Long tenantId,
                                                       @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = guard.resolveScopeTenant(u, tenantId);
        String accessToken = str(body == null ? null : body.get("accessToken"));
        String orgName = str(body == null ? null : body.get("orgName"));
        return ApiResponse.ok(tenantInitService.verify(u, scope, accessToken, orgName));
    }

    /**
     * 校验并初始化：{@code {accessToken?, orgName, enabled?, note?, rotateToken?}}。
     *
     * <p>rotateToken=false 且已有令牌、本次未传 accessToken 时复用已存令牌（只改组织名/开关）；
     * 否则 accessToken 必填并覆盖。失败即中止，已存在行仅标 FAILED + last_error，其余字段不变。</p>
     */
    @PostMapping("/init")
    public ApiResponse<Map<String, Object>> initInitialize(@RequestParam(required = false) Long tenantId,
                                                           @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = guard.resolveScopeTenant(u, tenantId);
        String accessToken = str(body == null ? null : body.get("accessToken"));
        String orgName = str(body == null ? null : body.get("orgName"));
        Boolean enabled = bool(body == null ? null : body.get("enabled"));
        String note = str(body == null ? null : body.get("note"));
        Boolean rotateToken = bool(body == null ? null : body.get("rotateToken"));
        return ApiResponse.ok(tenantInitService.initialize(u, scope, accessToken, orgName, enabled, note, rotateToken));
    }

    /**
     * 撤销企业令牌：清空 access_token/token_owner/token_scope/org_verified，init_status 复位 PENDING；
     * 保留 org_name 与 enabled（组织归属由 /tenant-config 管辖）。
     */
    @DeleteMapping("/init")
    public ApiResponse<Map<String, Object>> initRevoke(@RequestParam(required = false) Long tenantId) {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = guard.resolveScopeTenant(u, tenantId);
        return ApiResponse.ok(tenantInitService.revoke(u, scope));
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o).trim();
    }

    private static Boolean bool(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof Boolean b) {
            return b;
        }
        String s = String.valueOf(o).trim();
        if (s.isEmpty()) {
            return null;
        }
        return "true".equalsIgnoreCase(s) || "1".equals(s);
    }

    /** 可选部门（建项目时选择归属部门；受组织作用域限制）。 */
    @GetMapping("/departments")
    public ApiResponse<List<Map<String, Object>>> departments() {
        return ApiResponse.ok(projectService.selectableDepartments(guard.requireOrgUser()));
    }

    /** 异步任务队列概况（排障用，租户管理员可见）。 */
    @GetMapping("/tasks/stats")
    public ApiResponse<Map<String, Object>> taskStats() {
        guard.requireTenantAdmin();
        return ApiResponse.ok(taskService.stats());
    }

    /**
     * 手动触发一次成员校准。
     *
     * <p>定时校准是兜底手段，但排障时需要「立刻对一次账」，否则只能等下一个整点。
     * 租户管理员只能校准**本租户**项目；平台管理员可校准全部租户（运维视角）。</p>
     */
    @PostMapping("/calibrate")
    public ApiResponse<Map<String, Object>> calibrate() {
        AuthUser u = guard.requireTenantAdmin();
        Long scope = cn.aioa.security.PermissionCatalog.isPlatformAdmin(u) ? null : u.getTenantId();
        int n = syncScheduler.triggerCalibrateNow(scope);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("enqueued", n);
        m.put("scope", scope == null ? "ALL_TENANTS" : "TENANT:" + scope);
        m.put("note", "校准任务已入队，由后台队列限速执行；可在任务统计中查看进度");
        return ApiResponse.ok(m);
    }

    // ======================================================================
    // 项目
    // ======================================================================

    /** 项目列表。 */
    @GetMapping("/projects")
    public ApiResponse<Map<String, Object>> projects(@RequestParam(required = false) Long departmentId,
                                                     @RequestParam(required = false) String keyword) {
        AuthUser u = guard.requireOrgUser();
        List<GiteeProject> rows = projectService.list(u, departmentId, keyword);
        List<Map<String, Object>> items = new ArrayList<>();
        for (GiteeProject p : rows) {
            items.add(projectService.toView(p));
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("items", items);
        m.put("total", items.size());
        // 是否具备「创建项目」的能力：按权限码判定，而不是拿单个项目的 canManage 去推
        // （部门负责人对自己部门可管理，用空项目推会得出 false，把新建按钮误藏起来）
        m.put("canCreate", cn.aioa.security.PermissionCatalog.holds(u,
                cn.aioa.security.PermissionCatalog.PROJECT_MANAGE)
                && !cn.aioa.security.PermissionCatalog.isPlatformAdmin(u));
        return ApiResponse.ok(m);
    }

    /** 新建项目（同步返回「创建中」，建仓在后台完成）。 */
    @PostMapping("/projects")
    public ApiResponse<Map<String, Object>> createProject(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        GiteeProject p = projectService.create(u, body == null ? Map.of() : body);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("status", p.getStatus());
        m.put("repoName", p.getRepoName());
        m.put("project", projectService.toView(p));
        m.put("note", "仓库正在后台创建，稍后刷新即可看到仓库地址与 Webhook 状态");
        return ApiResponse.ok(m);
    }

    /** 项目详情（含仓库地址、Webhook 状态、成员、可管理标记）。 */
    @GetMapping("/projects/{projectId}")
    public ApiResponse<Map<String, Object>> projectDetail(@PathVariable Long projectId) {
        return ApiResponse.ok(projectService.detail(guard.requireOrgUser(), projectId));
    }

    /** 建仓失败后重试。 */
    @PostMapping("/projects/{projectId}/retry")
    public ApiResponse<Map<String, Object>> retryProject(@PathVariable Long projectId) {
        GiteeProject p = projectService.retry(guard.requireOrgUser(), projectId);
        return ApiResponse.ok(projectService.toView(p));
    }

    /**
     * 删除项目（软删）。
     *
     * @param purgeRepo 是否同时删除 Gitee 仓库；默认跟随配置（生产默认 **false**）。
     */
    @DeleteMapping("/projects/{projectId}")
    public ApiResponse<Map<String, Object>> deleteProject(@PathVariable Long projectId,
                                                          @RequestParam(required = false) Boolean purgeRepo) {
        boolean purge = purgeRepo == null ? props.isPurgeRepoOnDelete() : purgeRepo;
        projectService.softDelete(guard.requireOrgUser(), projectId, purge);
        return ApiResponse.ok(Map.of("deleted", true, "purgeRepo", purge,
                "note", purge ? "已标记删除 Gitee 仓库（不可恢复）" : "仅移除平台项目，Gitee 仓库保留"));
    }

    // ======================================================================
    // 成员
    // ======================================================================

    /** 项目成员列表。 */
    @GetMapping("/projects/{projectId}/members")
    public ApiResponse<Map<String, Object>> members(@PathVariable Long projectId) {
        List<Map<String, Object>> items = memberService.listForUser(guard.requireOrgUser(), projectId);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("items", items);
        m.put("total", items.size());
        return ApiResponse.ok(m);
    }

    /** 可添加成员候选（本租户已绑定 Gitee 的成员）。 */
    @GetMapping("/projects/{projectId}/members/candidates")
    public ApiResponse<Map<String, Object>> memberCandidates(@PathVariable Long projectId,
                                                             @RequestParam(required = false) String keyword) {
        List<Map<String, Object>> items = memberService.candidates(guard.requireOrgUser(), projectId, keyword);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("items", items);
        m.put("total", items.size());
        return ApiResponse.ok(m);
    }

    /** 添加成员（异步同步 Gitee 协作者权限）。 */
    @PostMapping("/projects/{projectId}/members")
    public ApiResponse<Map<String, Object>> addMember(@PathVariable Long projectId,
                                                      @RequestBody Map<String, Object> body) {
        var m = memberService.add(guard.requireOrgUser(), projectId, body == null ? Map.of() : body);
        Map<String, Object> out = memberService.toView(m);
        out.put("note", "权限同步已入队；若成员尚未绑定 Gitee 会显示 PENDING，绑定后自动补齐");
        return ApiResponse.ok(out);
    }

    /** 移除成员（异步回收 Gitee 协作者权限）。 */
    @DeleteMapping("/projects/{projectId}/members/{memberId}")
    public ApiResponse<Map<String, Object>> removeMember(@PathVariable Long projectId,
                                                         @PathVariable Long memberId) {
        memberService.remove(guard.requireOrgUser(), projectId, memberId);
        return ApiResponse.ok(Map.of("removed", true, "memberId", memberId,
                "note", "Gitee 权限回收任务已入队"));
    }

    // ======================================================================
    // 内容与事件
    // ======================================================================

    /** 分支列表。 */
    @GetMapping("/projects/{projectId}/branches")
    public ApiResponse<Map<String, Object>> branches(@PathVariable Long projectId) {
        return ApiResponse.ok(contentService.branches(guard.requireOrgUser(), projectId));
    }

    /** 目录 / 文件内容。 */
    @GetMapping("/projects/{projectId}/contents")
    public ApiResponse<Map<String, Object>> contents(@PathVariable Long projectId,
                                                     @RequestParam(required = false) String path,
                                                     @RequestParam(required = false) String ref) {
        return ApiResponse.ok(contentService.contents(guard.requireOrgUser(), projectId, path, ref));
    }

    /** 网页上传提交（提交方式①）。 */
    @PostMapping("/projects/{projectId}/contents")
    public ApiResponse<Map<String, Object>> upload(@PathVariable Long projectId,
                                                   @RequestBody Map<String, Object> body) {
        return ApiResponse.ok(contentService.upload(guard.requireOrgUser(), projectId,
                body == null ? Map.of() : body));
    }

    /** 提交记录（Webhook 回流 + 网页上传合流）。 */
    @GetMapping("/projects/{projectId}/commits")
    public ApiResponse<Map<String, Object>> commits(@PathVariable Long projectId,
                                                    @RequestParam(required = false) String branch,
                                                    @RequestParam(required = false) Integer page,
                                                    @RequestParam(required = false) Integer size) {
        return ApiResponse.ok(contentService.commits(guard.requireOrgUser(), projectId, branch, page, size));
    }

    /** 事件流（push / 合并请求 / 任务 / 评论）。 */
    @GetMapping("/projects/{projectId}/events")
    public ApiResponse<Map<String, Object>> events(@PathVariable Long projectId,
                                                   @RequestParam(required = false) String eventType,
                                                   @RequestParam(required = false) Integer page,
                                                   @RequestParam(required = false) Integer size) {
        return ApiResponse.ok(contentService.events(guard.requireOrgUser(), projectId, eventType, page, size));
    }
}
