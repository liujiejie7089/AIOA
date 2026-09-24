package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.AiSkill;
import cn.aioa.resource.entity.ExpertConfig;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.mapper.AiSkillMapper;
import cn.aioa.resource.service.CatalogService;
import cn.aioa.resource.service.ContentReviewService;
import cn.aioa.resource.service.ExpertConfigService;
import cn.aioa.security.PermissionCatalog;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.time.LocalDateTime;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 多租户专家配置（方案 P1 / B2–B6）。
 *
 * <pre>
 * GET    /api/v1/expert-config/experts                 —— 当前用户可见的专家（全局模板 + 本租户副本，带生效配置）
 * GET    /api/v1/expert-config/experts/{key}           —— 单个专家详情（含覆盖链路与来源）
 * GET    /api/v1/expert-config/experts/{key}/resolve   —— 只返回解析结果（验证「配置真实生效」用）
 * POST   /api/v1/expert-config/experts/{key}/config    —— 写入某层配置片段（merge=false 整体替换）
 * PUT    /api/v1/expert-config/experts/{key}/config    —— 局部更新某层配置片段（merge=true）
 * DELETE /api/v1/expert-config/experts/{key}/config    —— 删除某层配置片段
 * POST   /api/v1/expert-config/templates/{key}/import  —— 从全局模板导入为租户副本
 * GET    /api/v1/expert-config/templates               —— 全局模板清单
 * POST   /api/v1/expert-config/templates               —— 新建/更新全局模板（**仅平台管理员**）
 * DELETE /api/v1/expert-config/experts/{key}           —— 删除专家（平台管理员删全局模板 / 租户管理员删本租户副本）
 * </pre>
 *
 * <p>权限（V33 明确归属）：读接口对所有登录用户开放（按可见范围过滤）；
 * 写接口要求权限码 {@link PermissionCatalog#EXPERT_MANAGE}，即
 * <b>系统管理员 / 租户管理员 / 企业管理员</b>（{@code PermissionCatalog.rolesText("expert:manage")}），
 * 且只能改自己租户的配置。此前仅认 ROLE_ADMIN/ROLE_TENANT_ADMIN，
 * 企业管理员无法为自己的机构引入专家。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/expert-config")
@RequiredArgsConstructor
public class ExpertConfigController {

    private final ExpertConfigService configService;
    private final CatalogService catalogService;
    private final AiExpertMapper expertMapper;
    private final AiSkillMapper skillMapper;
    private final ContentReviewService reviewService;

    // ---------- 读 ----------

    /** 当前用户可见的专家列表（全局模板 + 本租户副本，按 enabled/visibleScope/sort 过滤）。 */
    @GetMapping("/experts")
    public ApiResponse<List<Map<String, Object>>> experts() {
        AuthUser user = AuthUserContext.get();
        if (user == null) {
            throw new BizException(401, "未登录");
        }
        Long tenantId = user.getTenantId();
        long tid = tenantId == null ? 0L : tenantId;

        List<AiExpert> rows = expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                .and(w -> w.eq(AiExpert::getTenantId, 0L).or().eq(AiExpert::getTenantId, tid))
                .orderByAsc(AiExpert::getSort));

        // 租户副本覆盖同名全局模板
        Map<String, AiExpert> byKey = new LinkedHashMap<>();
        for (AiExpert e : rows) {
            AiExpert exist = byKey.get(e.getExpertKey());
            if (exist == null || (e.getTenantId() != null && e.getTenantId() > 0)) {
                byKey.put(e.getExpertKey(), e);
            }
        }

        List<Map<String, Object>> out = new ArrayList<>();
        for (AiExpert e : byKey.values()) {
            ExpertConfigService.ResolvedConfig rc = configService.resolve(
                    tid, user.getInstitutionId(), user.getDepartmentId(), user.getUserId(), e.getExpertKey());
            if (!Boolean.TRUE.equals(rc.settings().getEnabled()) && !canManageExperts(user)) {
                continue; // 关闭的专家对普通用户不可见（管理员仍可见以便配置）
            }
            if (!visible(rc.settings().getVisibleScope(), user)) {
                continue;
            }
            // V34：待审的租户副本不对普通成员可见（创建者本人与管理员仍可见，便于跟踪审核进度）
            if (!reviewService.visible(e.getAuditStatus(), user, e.getCreatedBy())) {
                continue;
            }
            Map<String, Object> m = new LinkedHashMap<>(rc.toPayload());
            m.put("id", e.getId());
            m.put("name", e.getName());
            m.put("icon", e.getIcon());
            m.put("summary", e.getSummary());
            m.put("intro", e.getIntro());
            m.put("category", e.getCategory());
            m.put("templateVersion", e.getTemplateVersion());
            m.put("isTenantCopy", e.getTenantId() != null && e.getTenantId() > 0);
            out.add(m);
        }
        out.sort((a, b) -> Integer.compare(asInt(a.get("sort")), asInt(b.get("sort"))));
        return ApiResponse.ok(out);
    }

    /** 单个专家：详情 + 覆盖链路（每层片段）。 */
    @GetMapping("/experts/{key}")
    public ApiResponse<Map<String, Object>> detail(@PathVariable("key") String key) {
        AuthUser user = requireUser();
        Long tenantId = user.getTenantId();
        long tid = tenantId == null ? 0L : tenantId;
        ExpertConfigService.ResolvedConfig rc = configService.resolve(
                tid, user.getInstitutionId(), user.getDepartmentId(), user.getUserId(), key);
        Map<String, Object> m = new LinkedHashMap<>(rc.toPayload());
        m.put("layers", rc.layers());
        // V36 需求⑤：待审 / 已驳回的片段只对「有专家管理权的人」展示，
        // 普通用户看到的是真实生效的配置（resolve 已过滤），避免未审内容外泄。
        List<ExpertConfig> fragments = configService.list(tid, key);
        if (!canManageExperts(user)) {
            fragments = fragments.stream().filter(f -> ExpertConfig.effective(f.getAuditStatus())).toList();
        }
        m.put("fragments", fragments);
        return ApiResponse.ok(m);
    }

    /** 只返回解析结果：供 agent 与自检脚本核对「配置是否真实生效」。 */
    @GetMapping("/experts/{key}/resolve")
    public ApiResponse<Map<String, Object>> resolve(@PathVariable("key") String key,
                                                    @RequestParam(value = "userId", required = false) Long userId,
                                                    @RequestParam(value = "deptId", required = false) Long deptId,
                                                    @RequestParam(value = "institutionId", required = false) Long institutionId) {
        AuthUser user = requireUser();
        Long tenantId = user.getTenantId();
        long tid = tenantId == null ? 0L : tenantId;
        ExpertConfigService.ResolvedConfig rc = configService.resolve(
                tid, institutionId, deptId, userId, key);
        return ApiResponse.ok(rc.toPayload());
    }

    /** 全局模板清单（tenant_id=0）。 */
    @GetMapping("/templates")
    public ApiResponse<List<AiExpert>> templates() {
        requireUser();
        return ApiResponse.ok(expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, 0L)
                .orderByAsc(AiExpert::getSort)));
    }

    // ---------- 写 ----------

    public record ConfigBody(String scopeType, Long scopeId, Map<String, Object> config) {
    }

    /** 写入/替换某层配置片段。 */
    @PostMapping("/experts/{key}/config")
    public ApiResponse<Map<String, Object>> save(@PathVariable("key") String key,
                                                 @RequestBody ConfigBody body) {
        AuthUser user = requireAdmin();
        String audit = reviewService.configInitialStatus(user, body.scopeType());
        ExpertConfig row = configService.save(user.getTenantId(), body.scopeType(), body.scopeId(),
                key, body.config(), false, user.getUserId(), audit);
        return ApiResponse.ok(configSaved(row, audit));
    }

    /** 局部更新某层配置片段（只覆盖传入的键）。 */
    @PutMapping("/experts/{key}/config")
    public ApiResponse<Map<String, Object>> patch(@PathVariable("key") String key,
                                                  @RequestBody ConfigBody body) {
        AuthUser user = requireAdmin();
        String audit = reviewService.configInitialStatus(user, body.scopeType());
        ExpertConfig row = configService.save(user.getTenantId(), body.scopeType(), body.scopeId(),
                key, body.config(), true, user.getUserId(), audit);
        return ApiResponse.ok(configSaved(row, audit));
    }

    /** 删除某层配置片段。 */
    @DeleteMapping("/experts/{key}/config")
    public ApiResponse<Boolean> delete(@PathVariable("key") String key,
                                       @RequestParam("scopeType") String scopeType,
                                       @RequestParam(value = "scopeId", required = false) Long scopeId) {
        AuthUser user = requireAdmin();
        configService.delete(user.getTenantId(), scopeType, scopeId, key);
        return ApiResponse.ok(true);
    }

    /** 从全局模板导入为租户副本（已存在则更新，不重复创建）。 */
    @PostMapping("/templates/{key}/import")
    public ApiResponse<Map<String, Object>> importTemplate(@PathVariable("key") String key) {
        AuthUser user = requireAdmin();
        Long tenantId = user.getTenantId();
        if (tenantId == null || tenantId <= 0) {
            throw BizException.badRequest("平台级账号无租户上下文，无法导入租户副本");
        }
        AiExpert tpl = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, 0L)
                .eq(AiExpert::getExpertKey, key));
        if (tpl == null) {
            throw BizException.notFound("全局模板不存在：" + key);
        }
        AiExpert copy = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, tenantId)
                .eq(AiExpert::getExpertKey, key));
        boolean created = copy == null;
        if (created) {
            copy = new AiExpert();
            copy.setTenantId(tenantId);
            copy.setExpertKey(key);
            copy.setCreatedBy(user.getUserId());
        }
        copy.setName(tpl.getName());
        copy.setIcon(tpl.getIcon());
        copy.setSummary(tpl.getSummary());
        copy.setIntro(tpl.getIntro());
        copy.setTags(tpl.getTags());
        copy.setRecs(tpl.getRecs());
        copy.setAgentCode(tpl.getAgentCode());
        copy.setCategory(tpl.getCategory());
        copy.setTemplateVersion(tpl.getTemplateVersion());
        copy.setSourceTemplateId(tpl.getId());
        copy.setVisibleScope(tpl.getVisibleScope());
        copy.setKbScope(tpl.getKbScope());
        copy.setDefaultEnabled(tpl.getDefaultEnabled());
        copy.setEnabled(true);
        copy.setSort(tpl.getSort());
        // V34：新建的租户副本需平台管理员审核；再次导入（已存在）视为更新，若此前已通过则保持通过
        if (created) {
            copy.setAuditStatus(reviewService.initialStatus(user));
        } else if (copy.getAuditStatus() == null || copy.getAuditStatus().isBlank()) {
            copy.setAuditStatus(ContentReviewService.APPROVED);
        }
        if (created) {
            expertMapper.insert(copy);
        } else {
            expertMapper.updateById(copy);
        }
        log.info("expert template imported: tenant={} key={} created={}", tenantId, key, created);
        return ApiResponse.ok(Map.of("id", copy.getId(), "expertKey", key, "created", created));
    }

    /** 平台管理员新建 / 更新全局模板的入参。{@code config} 为运行参数（落 GLOBAL 层片段）。 */
    public record TemplateBody(
            String key, String name, String icon, String summary, String intro,
            List<Object> tags, List<Object> recs, String category, String agentCode,
            String templateVersion, String visibleScope, String kbScope, Boolean defaultEnabled,
            Integer sort, Map<String, Object> config) {
    }

    /**
     * 平台管理员新建 / 更新一个**全局专家模板**（写入 {@code tenant_id=0}）。
     *
     * <p>本端点是「模板」这一能力的**唯一产入口**。在它之前，{@code tenant_id=0} 的模板只能由
     * seed 脚本（{@code scripts/seed_expert_templates.py}）与迁移（V62）写入 ——
     * 管理端既不能新建模板、也不能把自建专家发布为模板，
     * 于是「租户从模板导入」面对的是一个**冻结的模板库**。
     * 补上产入口后，读（{@link #templates()}）— 产（本方法）— 消费（{@link #importTemplate}）三者闭环。</p>
     *
     * <p>权限：**仅平台管理员**。租户 / 企业管理员不应能改全局模板（那是全平台共享内容）；
     * 他们的入口是「从模板导入」，得到的是**本租户副本**（{@code source_template_id} 指回本模板）。</p>
     *
     * <p>幂等：按唯一键 {@code (tenant_id=0, expert_key)} upsert —— 重复提交同一 key 是
     * 「更新模板」，不报错也不产生第二份。已导入的租户副本**不会**被自动同步：
     * 租户副本是独立行，需租户再点一次「导入」才更新，避免平台改模板时误改租户的在架内容。</p>
     */
    @PostMapping("/templates")
    public ApiResponse<Map<String, Object>> saveTemplate(@RequestBody(required = false) TemplateBody body) {
        AuthUser user = requireUser();
        if (!PermissionCatalog.isPlatformAdmin(user)) {
            throw BizException.forbidden("只有平台管理员可以新建/修改全局专家模板（全平台共享）。"
                    + "租户请用「从模板导入」，得到本租户副本后自行调整");
        }
        if (body == null || body.name() == null || body.name().isBlank()) {
            throw BizException.badRequest("模板名称（name）必填");
        }
        String key = normalizeTemplateKey(body.key());

        AiExpert row = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, 0L)
                .eq(AiExpert::getExpertKey, key));
        boolean created = row == null;
        if (created) {
            row = new AiExpert();
            row.setTenantId(0L);
            row.setExpertKey(key);
            row.setCreatedBy(user.getUserId());
        }
        row.setName(body.name().trim());
        row.setIcon(blankTo(body.icon(), "🧠"));
        row.setSummary(blankTo(body.summary(), ""));
        row.setIntro(blankTo(body.intro(), ""));
        row.setTags(body.tags());
        row.setRecs(body.recs());
        row.setAgentCode(body.agentCode());
        row.setCategory(blankTo(body.category(), "GENERAL").toUpperCase());
        row.setTemplateVersion(blankTo(body.templateVersion(), "1.0"));
        row.setSourceTemplateId(null);                                  // 全局模板不指向别的模板
        row.setVisibleScope(blankTo(body.visibleScope(), "ALL").toUpperCase());
        row.setKbScope(blankTo(body.kbScope(), "ALL"));
        row.setDefaultEnabled(Boolean.TRUE.equals(body.defaultEnabled()));
        // 「新建即可不启用」：以 config.enabled 为唯一意图来源（缺省启用，保持既有行为）。
        // 此前硬编码 true ⇒ 管理员即便想先建后审也建不出「未启用」的专家。
        row.setEnabled(enabledIntent(body.config()));
        row.setSort(body.sort() == null ? 100 : body.sort());
        // 平台管理员自建即生效：内容是平台自己写的，不需要「自己审自己」
        row.setAuditStatus(ContentReviewService.APPROVED);
        row.setAuditNote(null);
        row.setReviewedBy(user.getUserId());
        row.setReviewedAt(LocalDateTime.now());
        if (created) {
            expertMapper.insert(row);
        } else {
            expertMapper.updateById(row);
        }

        // 运行参数落 GLOBAL 层片段，口径与 seed 脚本一致：tenant=0 / scope=GLOBAL / scopeId=0。
        // 租户导入副本后靠 resolve() 回落继承这段配置（importTemplate 不复制 expert_config 行）。
        boolean hasConfig = body.config() != null && !body.config().isEmpty();
        if (hasConfig) {
            configService.save(0L, ExpertConfig.GLOBAL, 0L, key, body.config(), false,
                    user.getUserId(), ExpertConfig.AUDIT_APPROVED);
        }
        log.info("expert template saved: key={} created={} withConfig={}", key, created, hasConfig);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.getId());
        out.put("expertKey", key);
        out.put("created", created);
        out.put("templateVersion", row.getTemplateVersion());
        out.put("hint", created
                ? "模板已创建，租户端「从模板导入」即可看到并导入"
                : "模板已更新；已导入的租户副本不会自动同步，需租户再次导入");
        return ApiResponse.ok(out);
    }

    /**
     * 删除专家。
     *
     * <p><b>删的是「调用者自己名下的那一行」</b>，与列表口径同源（铁律 #1）：
     * 平台管理员 → 全局模板（{@code tenant_id=0}）；租户 / 企业管理员 → 本租户副本。
     * 这也解释了平台管理员的列表里只有全局模板 —— 他没有「别人的租户副本」可删。</p>
     *
     * <p><b>级联</b>：{@code expert_config} 中该 {@code expert_key} 的片段
     * + 挂靠它的 {@code ai_skill} 行。不做级联会让同一 key 日后被重建时旧片段
     * <b>静默复活</b>（表现为「新建的专家一上来就是关的 / 提示词是上一轮留下的」）。</p>
     *
     * <p>片段要分两段清：先清<b>调用者自己名下</b>的（{@link ExpertConfigService#deleteAll}），
     * 再在「该 key 已全局消失」时清<b>跨租户的孤儿片段</b>
     * （{@link ExpertConfigService#deleteAllExceptTenants}，保留仍持有副本的租户）。
     * 只清前者会漏掉「某租户没导入副本、只是把它停用过」而留下的片段 ——
     * 实测正是这条会在重建时把新专家置为「关」。</p>
     *
     * <p><b>守卫</b>（都返回明确文案，绝不静默成功）：</p>
     * <ul>
     *   <li><b>默认 AI 不可删</b> —— 否则用户端「未选功能」时会落到一个已不存在的专家；
     *       判据与目录兜底同源（{@link CatalogService#defaultExpertKey}），不另判一次；</li>
     *   <li><b>全局模板已被租户导入</b> —— 默认拒绝并告知副本数量，需显式 {@code force=true}
     *       才继续，避免一次点击静默让多个租户的目录缺角。</li>
     * </ul>
     */
    @DeleteMapping("/experts/{key}")
    public ApiResponse<Map<String, Object>> deleteExpert(@PathVariable("key") String key,
                                                         @RequestParam(value = "force", required = false) Boolean force) {
        AuthUser user = requireAdmin();
        long tid = user.getTenantId() == null ? 0L : user.getTenantId();

        AiExpert row = expertMapper.selectOne(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, tid)
                .eq(AiExpert::getExpertKey, key));
        if (row == null) {
            throw BizException.notFound("未找到可删除的专家：" + key
                    + (tid == 0L ? "（平台管理员删除的是全局模板）" : "（租户管理员删除的是本租户副本）"));
        }

        // 守卫①：默认 AI 不可删（判据与用户端兜底同源）
        if (key.equals(catalogService.defaultExpertKey(tid))) {
            throw BizException.badRequest("「" + row.getName() + "」当前是默认 AI，不能删除；"
                    + "请先把默认 AI 换成其他专家，再删除它");
        }

        // 守卫②：删全局模板前确认没有租户已导入副本
        List<AiExpert> copies = List.of();
        if (tid == 0L) {
            copies = expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                    .ne(AiExpert::getTenantId, 0L)
                    .eq(AiExpert::getExpertKey, key));
            if (!copies.isEmpty() && !Boolean.TRUE.equals(force)) {
                // 用 409 而不是 400：前端据此判断「这是可 force 的软拒绝」并弹二次确认，
                // 无需去匹配文案（GlobalExceptionHandler 只把 401/403/404 映射成 HTTP 状态，
                // 409 仍是 HTTP 200 + code=409，走统一信封）。
                throw new BizException(409, "该模板已被 " + copies.size()
                        + " 个租户导入为副本，删除后它们仍需自行处理；如确认要删，请带 force=true 重试");
            }
        }

        // 级联：配置片段 + 挂靠技能（都是物理删除，理由见两个 mapper 的注释）
        int purgedConfigs = configService.deleteAll(tid, key);
        int purgedSkills = skillMapper.hardDeleteByExpert(tid, key);
        int deletedRows = expertMapper.hardDeleteById(row.getId());
        if (deletedRows == 0) {
            // 并发下被别人先删了：不静默，明确告知本次未删到东西
            throw BizException.notFound("专家已被删除或不存在：" + key);
        }

        // 级联兜底：清掉**跨租户的孤儿片段**。
        // 为什么需要：deleteAll(tid, key) 只清了调用者自己名下的片段，而租户可以在
        // **没有导入副本**的情况下写过片段（典型：某租户把这个专家停用了，
        // 落一条 expert_config(tenant_id=2, expert_key=x, enabled=false)）。
        // 这些片段留着不会「立刻」出错，但同一 key 日后重建时会**静默复活** ——
        // 新专家在那个租户那里一上来就是「关」的，正是本轮用户报的那类缺陷。
        //
        // 只在「该 key 已全局消失」时才清：全局模板仍在时，各租户对它的覆盖片段
        // （含「本租户停用它」）依然有意义，动了就是删别人的数据。
        List<Long> aliveTenants = expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                        .eq(AiExpert::getExpertKey, key))
                .stream().map(AiExpert::getTenantId).distinct().collect(Collectors.toList());
        if (!aliveTenants.contains(0L)) {
            purgedConfigs += configService.deleteAllExceptTenants(key, aliveTenants);
        }

        log.info("expert deleted: tenant={} expert={} by={} configs={} skills={} copiesLeft={}",
                tid, key, user.getUsername(), purgedConfigs, purgedSkills, copies.size());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("expertKey", key);
        out.put("name", row.getName());
        out.put("tenantId", tid);
        out.put("purgedConfigs", purgedConfigs);
        out.put("purgedSkills", purgedSkills);
        out.put("tenantCopiesLeft", copies.size());
        out.put("hint", tid == 0L
                ? "全局模板已删除；已导入该模板的租户副本需各自删除"
                : "本租户副本已删除（全局模板不受影响）");
        return ApiResponse.ok(out);
    }

    // ---------- 内部 ----------

    /**
     * 保存回执。
     *
     * <p>必须回 {@code auditStatus}：租户管理员保存后看到 {@code PENDING} 才知道
     * 「配置还没生效、等人审」，否则会误判为保存失败而反复重试（需求⑤）。</p>
     */
    private static Map<String, Object> configSaved(ExpertConfig row, String auditStatus) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.getId());
        out.put("scopeType", row.getScopeType());
        out.put("scopeId", row.getScopeId());
        out.put("expertKey", row.getExpertKey());
        out.put("auditStatus", row.getAuditStatus() == null ? auditStatus : row.getAuditStatus());
        out.put("effective", ExpertConfig.effective(row.getAuditStatus()));
        out.put("hint", ExpertConfig.effective(row.getAuditStatus())
                ? "配置已生效"
                : "已提交平台管理员审核，审核通过后生效（当前仍使用原配置）");
        return out;
    }

    /** 模板标识允许的形态：小写字母开头、2–32 位、仅 a-z0-9_（与 seed 脚本的 legal / data_analyst 同口径）。 */
    private static final Pattern TEMPLATE_KEY_RE = Pattern.compile("^[a-z][a-z0-9_]{1,31}$");

    /**
     * 校验并规范化模板 key。
     *
     * <p>为什么要卡格式：key 既是 {@code ai_expert} 唯一键的一半，又出现在 URL 路径里
     * （{@code /templates/{key}/import}），放任意字符串会带来路径歧义；
     * H5 深链 {@code ?expert=<key>} 也直接用它。seed 脚本产出的 key 全部满足本规则。</p>
     */
    private static String normalizeTemplateKey(String raw) {
        String key = raw == null ? "" : raw.trim().toLowerCase();
        if (ExpertConfig.WILDCARD.equals(key)) {
            throw BizException.badRequest("`*` 是全局默认配置片段的保留标识，不能作为专家 key");
        }
        if (!TEMPLATE_KEY_RE.matcher(key).matches()) {
            throw BizException.badRequest("模板标识（key）必须是小写字母开头的 2–32 位 a-z0-9_"
                    + "（如 legal / data_analyst）；收到：" + raw);
        }
        return key;
    }

    private static String blankTo(String v, String fallback) {
        return v == null || v.isBlank() ? fallback : v.trim();
    }

    /**
     * 从模板入参的 {@code config} 片段读「是否启用」意图；缺省视为启用。
     *
     * <p>只认字符串 {@code "false"} 为关闭，避免 {@code get("enabled")} 在不同
     * 序列化形态（Boolean / "false"）下判断分叉。</p>
     */
    private static boolean enabledIntent(Map<String, Object> config) {
        if (config == null) {
            return true;
        }
        Object v = config.get("enabled");
        return v == null || !"false".equalsIgnoreCase(String.valueOf(v));
    }

    private AuthUser requireUser() {
        AuthUser user = AuthUserContext.get();
        if (user == null) {
            throw new BizException(401, "未登录");
        }
        return user;
    }

    private AuthUser requireAdmin() {
        AuthUser user = requireUser();
        if (!PermissionCatalog.holds(user, PermissionCatalog.EXPERT_MANAGE)) {
            throw BizException.forbidden("专家创建与配置需要权限「专家管理」，可由"
                    + PermissionCatalog.rolesText(PermissionCatalog.EXPERT_MANAGE) + "执行");
        }
        return user;
    }

    /** 是否具备专家管理权限（系统管理员 / 租户管理员 / 企业管理员）。 */
    private static boolean canManageExperts(AuthUser user) {
        return PermissionCatalog.holds(user, PermissionCatalog.EXPERT_MANAGE);
    }

    /** 可见范围判定：ALL 全员；其余按层级比对当前用户所属作用域。 */
    private static boolean visible(String scope, AuthUser user) {
        if (scope == null || scope.isBlank() || "ALL".equalsIgnoreCase(scope)) {
            return true;
        }
        String s = scope.toUpperCase();
        Long v = switch (s) {
            case "TENANT" -> user.getTenantId();
            case "INSTITUTION" -> user.getInstitutionId();
            case "DEPT" -> user.getDepartmentId();
            case "USER" -> user.getUserId();
            default -> null;
        };
        return v != null && v > 0;
    }

    private static int asInt(Object v) {
        return v instanceof Number n ? n.intValue() : 100;
    }
}
