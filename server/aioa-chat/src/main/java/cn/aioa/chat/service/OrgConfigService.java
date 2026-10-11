package cn.aioa.chat.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.entity.SysOrgConfig;
import cn.aioa.resource.mapper.SysConfigMapper;
import cn.aioa.resource.mapper.SysOrgConfigMapper;
import cn.aioa.resource.support.SysConfigGroups;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 机构作用域系统参数（需求二 · 管理端菜单权限，docs/44 §2.5 B 案）。
 *
 * <p><b>为什么放在 aioa-chat 而不是 aioa-resource</b>：本服务要同时访问
 * aioa-resource（{@code sys_config} / {@code sys_org_config} 的实体与 Mapper）与 aioa-org
 * （{@code org_institution} 按租户查机构），这两个模块互不依赖，
 * 只有 aioa-chat 同时依赖二者 —— 与 {@code WorkerIntakeService} / {@code StatsController} 同一理由。
 * 端点路径仍是 {@code /api/v1/admin/org-configs}，归属语义不变，只是实现落在唯一可见两个域的模块里。</p>
 *
 * <p><b>作用域硬边界（本需求要点）</b>：机构管理员（{@code ROLE_ORG_ADMIN} 且非平台/租户管理员）
 * 的 {@code institution_id} 被<b>钉死</b>为本机构，前端传别的机构 → 403（不是静默降级）；
 * 未绑机构 → 403。平台/租户管理员可切机构，但所选机构必须属本租户，否则 403/404。
 * 所有写操作的 {@code tenant_id} 一律取登录态，不接受前端入参（防改包提权）。</p>
 *
 * <p><b>作用域解析是唯一判定点</b>：见 {@link #resolveScopeInstitution(AuthUser, Long, Set)} 与
 * {@link #resolveWriteScope(AuthUser, Long, Set)}。控制器不再分散判定，否则会出现「两处口径」。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrgConfigService {

    private final SysConfigMapper configMapper;
    private final SysOrgConfigMapper orgConfigMapper;
    private final OrgInstitutionMapper institutionMapper;

    // ========================================================================
    // 纯函数：作用域解析（唯一判定点，可单测、不依赖 Spring）
    // ========================================================================

    /**
     * 机构作用域解析的<b>唯一判定点</b>。把所有作用域规则集中到这一个函数，避免控制器里散落判定。
     *
     * @param user               当前用户
     * @param requested         前端传入的 institutionId（可空；空表示「未选择」）
     * @param tenantInstitutions 本租户全部机构 ID 集合（用于校验跨租户）
     * @return 解析后的机构 ID；若 requested 为空且调用者可切机构，返回 {@code null}
     *         （由调用点判空：GET 返回空 items / PUT·DELETE 抛 400「请先选择机构」）
     * @throws BizException 越权/越界：机构管理员传别的机构 → 403；未绑机构 → 403；跨租户 → 403
     */
    static Long resolveScopeInstitution(AuthUser user, Long requested, Set<Long> tenantInstitutions) {
        if (institutionScoped(user)) {
            Long mine = user.getInstitutionId();
            if (mine == null) {
                throw BizException.forbidden("账号未绑定机构，无法配置机构参数");
            }
            if (requested != null && !requested.equals(mine)) {
                throw BizException.forbidden("机构管理员只能配置本机构（institutionId="
                        + mine + "）的参数，不能操作其它机构（" + requested + "）");
            }
            return mine;
        }
        // 平台/租户管理员：可切机构
        if (requested == null) {
            return null; // 未选择，由调用点判空
        }
        if (tenantInstitutions == null || !tenantInstitutions.contains(requested)) {
            throw BizException.forbidden("机构 " + requested + " 不属于当前租户，无法配置其参数");
        }
        return requested;
    }

    /**
     * 写操作作用域解析：未选机构且可切机构 → 400「请先选择机构」。
     *
     * <p>机构管理员即便省略也钉死本机构（{@link #resolveScopeInstitution} 返回非 null），
     * 不会触发本分支；只有平台/租户管理员省略时才需 400。</p>
     */
    static Long resolveWriteScope(AuthUser user, Long requested, Set<Long> tenantInstitutions) {
        Long resolved = resolveScopeInstitution(user, requested, tenantInstitutions);
        if (resolved == null) {
            throw BizException.badRequest("请先选择机构");
        }
        return resolved;
    }

    /** 企业管理员（且不是平台/租户管理员）：数据范围收紧到本机构。照抄 {@code AdminWorkerController#institutionScoped}。 */
    private static boolean institutionScoped(AuthUser user) {
        return PermissionCatalog.hasRole(user, PermissionCatalog.ROLE_ORG_ADMIN)
                && !PermissionCatalog.hasRole(user, PermissionCatalog.ROLE_TENANT_ADMIN)
                && !PermissionCatalog.isPlatformAdmin(user);
    }

    // ========================================================================
    // 业务方法
    // ========================================================================

    /** 读某机构的参数（含继承状态）。 */
    public OrgConfigReadResult read(AuthUser user, Long requestedInstitutionId) {
        requireManage(user);
        Long tenantId = tenantIdOf(user);
        Set<Long> tenantInstitutions = loadTenantInstitutionIds(tenantId);
        boolean scoped = institutionScoped(user);

        Long institutionId = resolveScopeInstitution(user, requestedInstitutionId, tenantInstitutions);

        OrgConfigReadResult result = new OrgConfigReadResult();
        result.setInstitutions(buildInstitutions(user, tenantId, scoped));
        result.setScopeLocked(scoped);
        result.setCanManage(true);
        result.setInstitutionId(institutionId); // 可能为 null（可切机构且未选）
        result.setGroups(SysConfigGroups.NAMES); // 分组中文名（与「系统参数」页同源，避免两页风格不一致）
        if (institutionId == null) {
            result.setItems(List.of());
            return result;
        }
        result.setItems(buildItems(tenantId, institutionId));
        return result;
    }

    /** upsert 覆盖值（机构管理员被钉死本机构）。 */
    public void upsert(AuthUser user, OrgConfigUpsertReq req) {
        requireManage(user);
        if (req == null || req.getConfigKey() == null || req.getConfigKey().isBlank()) {
            throw BizException.badRequest("缺少参数键 configKey");
        }
        Long tenantId = tenantIdOf(user);
        Set<Long> tenantInstitutions = loadTenantInstitutionIds(tenantId);
        Long institutionId = resolveWriteScope(user, req.getInstitutionId(), tenantInstitutions);

        SysConfig def = requireTenantConfig(tenantId, req.getConfigKey());
        String value = req.getConfigValue() == null ? "" : req.getConfigValue();

        SysOrgConfig existing = selectOne(tenantId, institutionId, req.getConfigKey());
        if (existing == null) {
            SysOrgConfig row = new SysOrgConfig();
            row.setTenantId(tenantId);
            row.setInstitutionId(institutionId);
            row.setConfigKey(req.getConfigKey());
            row.setConfigName(def.getConfigName());
            row.setGroupCode(def.getGroupCode());
            row.setValueType(def.getValueType());
            row.setConfigValue(value);
            row.setCreatedBy(user.getUserId());
            row.setCreatedAt(LocalDateTime.now());
            orgConfigMapper.insert(row);
        } else {
            existing.setConfigValue(value);
            existing.setConfigName(def.getConfigName());
            existing.setGroupCode(def.getGroupCode());
            existing.setValueType(def.getValueType());
            existing.setUpdatedAt(LocalDateTime.now());
            orgConfigMapper.updateById(existing);
        }
    }

    /** 删除覆盖值 → 恢复继承。 */
    public void delete(AuthUser user, Long institutionId, String configKey) {
        requireManage(user);
        if (configKey == null || configKey.isBlank()) {
            throw BizException.badRequest("缺少参数键 configKey");
        }
        Long tenantId = tenantIdOf(user);
        Set<Long> tenantInstitutions = loadTenantInstitutionIds(tenantId);
        Long resolved = resolveWriteScope(user, institutionId, tenantInstitutions);

        requireTenantConfig(tenantId, configKey); // 未知键 → 400

        SysOrgConfig existing = selectOne(tenantId, resolved, configKey);
        if (existing != null) {
            // 删除即物理删：覆盖行无审计价值，「恢复继承」就是它的语义（无需软删残留死行）。
            orgConfigMapper.deleteById(existing.getId());
        }
    }

    // ========================================================================
    // 内部
    // ========================================================================

    private void requireManage(AuthUser user) {
        if (!PermissionCatalog.holds(user, PermissionCatalog.ORG_CONFIG_MANAGE)) {
            throw BizException.forbidden("机构参数配置需要「机构参数配置」权限（"
                    + PermissionCatalog.rolesText(PermissionCatalog.ORG_CONFIG_MANAGE)
                    + "）；当前账号角色为「"
                    + String.join("、", user.getRoles() == null ? List.of() : user.getRoles()) + "」");
        }
    }

    /**
     * 取登录态的租户 ID。
     *
     * <p>平台管理员 {@code getTenantId()} 为空时兜底 0L，与既有 {@code AdminConfigController} /
     * {@code ConfigController} 同口径；本期<b>不</b>实现跨租户浏览
     * （需求只要求机构管理员为本机构配置，平台/租户管理员也只配本租户机构）。</p>
     */
    private static Long tenantIdOf(AuthUser user) {
        return user.getTenantId() == null ? 0L : user.getTenantId();
    }

    private Set<Long> loadTenantInstitutionIds(Long tenantId) {
        return institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                        .eq(OrgInstitution::getTenantId, tenantId))
                .stream()
                .map(OrgInstitution::getId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
    }

    // 包级私有：便于 OrgConfigScopeTest 在不启动 Spring 上下文的前提下，直接定点验证机构清单分支
    // （scoped 条件一旦写反，单测立刻变红）。
    List<InstitutionDTO> buildInstitutions(AuthUser user, Long tenantId, boolean scoped) {
        if (scoped) {
            // scoped==true 即机构管理员（作用域被钉死为本机构）：只返回本人那一个
            Long mine = user.getInstitutionId();
            OrgInstitution inst = mine == null ? null : institutionMapper.selectById(mine);
            InstitutionDTO dto = new InstitutionDTO();
            dto.setId(mine);
            dto.setName(inst != null ? inst.getName() : null);
            return List.of(dto);
        }
        // scoped==false 即平台/租户管理员：本租户全部机构，按 id 升序
        List<OrgInstitution> all = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId)
                .orderByAsc(OrgInstitution::getId));
        // 查询层已 orderByAsc，这里再做一次内存排序兜底，保证「按 id 升序」契约由方法自身保证
        // （而非依赖入参顺序），也便于单测直接断言升序。
        all.sort(Comparator.comparing(OrgInstitution::getId));
        List<InstitutionDTO> dtos = new ArrayList<>();
        for (OrgInstitution o : all) {
            InstitutionDTO d = new InstitutionDTO();
            d.setId(o.getId());
            d.setName(o.getName());
            dtos.add(d);
        }
        return dtos;
    }

    /**
     * 机构参数项列表：键集与顺序 = 该租户 sys_config 的键集（含平台模板 tenant_id=0 的键，union 去重）。
     * 模板键在前、租户键覆盖同键的展示信息；按 group_code, sort_no 排序。
     */
    private List<ItemDTO> buildItems(Long tenantId, Long institutionId) {
        Map<String, SysConfig> byKey = new LinkedHashMap<>();
        for (SysConfig t : configMapper.selectList(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, 0L))) {
            byKey.put(t.getConfigKey(), t);
        }
        for (SysConfig t : configMapper.selectList(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, tenantId))) {
            byKey.put(t.getConfigKey(), t); // 租户覆盖模板（同键）
        }

        List<SysConfig> ordered = new ArrayList<>(byKey.values());
        ordered.sort(Comparator.comparing(
                        (SysConfig c) -> c.getGroupCode() == null ? "" : c.getGroupCode())
                .thenComparingInt((SysConfig c) -> c.getSortNo() == null ? 0 : c.getSortNo()));

        List<ItemDTO> items = new ArrayList<>();
        for (SysConfig c : ordered) {
            String key = c.getConfigKey();
            if (key == null || key.isBlank()) {
                continue;
            }
            ItemDTO it = new ItemDTO();
            it.setConfigKey(key);
            it.setConfigName(c.getConfigName());
            it.setGroupCode(c.getGroupCode());
            it.setValueType(c.getValueType());
            String tenantValue = resolveTenantValue(tenantId, key);
            it.setTenantValue(tenantValue);
            SysOrgConfig orgRow = selectOne(tenantId, institutionId, key);
            String orgValue = orgRow != null ? orgRow.getConfigValue() : null;
            it.setOrgValue(orgValue);
            it.setEffectiveValue(orgValue != null ? orgValue : tenantValue);
            it.setOverridden(orgValue != null);
            items.add(it);
        }
        return items;
    }

    /** 租户值 → 平台默认（tenant_id=0）→ 空串。照抄 {@code ConfigController#resolve} 口径。 */
    private String resolveTenantValue(Long tenantId, String key) {
        for (Long scope : List.of(tenantId, 0L)) {
            SysConfig row = configMapper.selectOne(new LambdaQueryWrapper<SysConfig>()
                    .eq(SysConfig::getTenantId, scope)
                    .eq(SysConfig::getConfigKey, key)
                    .last("LIMIT 1"));
            if (row == null) {
                continue;
            }
            String value = row.getConfigValue();
            if (value == null || value.isBlank()) {
                value = row.getDefaultValue();
            }
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    /** configKey 必须是该租户（或平台模板）sys_config 里存在的键，否则 400。 */
    private SysConfig requireTenantConfig(Long tenantId, String key) {
        SysConfig row = configMapper.selectOne(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, tenantId)
                .eq(SysConfig::getConfigKey, key)
                .last("LIMIT 1"));
        if (row == null) {
            row = configMapper.selectOne(new LambdaQueryWrapper<SysConfig>()
                    .eq(SysConfig::getTenantId, 0L)
                    .eq(SysConfig::getConfigKey, key)
                    .last("LIMIT 1"));
        }
        if (row == null) {
            throw BizException.badRequest("未知参数键：" + key);
        }
        return row;
    }

    private SysOrgConfig selectOne(Long tenantId, Long institutionId, String configKey) {
        return orgConfigMapper.selectOne(new LambdaQueryWrapper<SysOrgConfig>()
                .eq(SysOrgConfig::getTenantId, tenantId)
                .eq(SysOrgConfig::getInstitutionId, institutionId)
                .eq(SysOrgConfig::getConfigKey, configKey)
                .last("LIMIT 1"));
    }

    // ========================================================================
    // DTO
    // ========================================================================

    /** GET 响应。 */
    @Data
    public static class OrgConfigReadResult {
        private List<InstitutionDTO> institutions;
        private boolean scopeLocked;
        private boolean canManage;
        private Long institutionId;
        private List<ItemDTO> items;
        /** 分组码 → 中文名（与「系统参数」页同源，展示顺序 = 插入序）。 */
        private Map<String, String> groups;
    }

    /** 可选机构（{@code id} / {@code name}）。 */
    @Data
    public static class InstitutionDTO {
        private Long id;
        private String name;
    }

    /** 单个参数项（含继承状态）。字段名与前端契约逐字一致。 */
    @Data
    public static class ItemDTO {
        private String configKey;
        private String configName;
        private String groupCode;
        private String valueType;
        private String tenantValue;
        private String orgValue;
        private String effectiveValue;
        private boolean overridden;
    }

    /** PUT 请求体：{@code {institutionId?, configKey, configValue}}。 */
    @Data
    public static class OrgConfigUpsertReq {
        private Long institutionId;
        private String configKey;
        private String configValue;
    }
}
