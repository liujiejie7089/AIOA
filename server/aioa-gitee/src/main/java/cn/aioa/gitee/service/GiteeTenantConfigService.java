package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.client.RepoProviderException;
import cn.aioa.gitee.client.RepoProviderClient;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteeAccount;
import cn.aioa.gitee.entity.GiteeTenantConfig;
import cn.aioa.gitee.mapper.GiteeTenantConfigMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 每租户 Gitee 组织的解析与配置服务 —— <b>org 解析的唯一真源</b>。
 *
 * <p><b>为什么是「唯一真源」</b>：此前 {@code props.getOrg()} 散落在建仓、建团队、Webhook
 * 等多处。一旦改为「每租户各自组织」，任何一处仍直接读 {@code props.getOrg()} 都会拿到
 * 错误的全局值。因此<b>此后任何业务代码都不得再读 {@code props.getOrg()}</b> 来决定仓库归属，
 * 一律走本服务的 {@link #effectiveOrg(Long)}。本类是唯一允许在读 {@code props.getOrg()}
 * 之外做回落判断的地方。</p>
 *
 * <p><b>回落语义（刻意保留全局默认）</b>：没配置、或 org 留空的租户，回落到
 * {@code aioa.gitee.org}，从而不破坏任何既有项目、演示租户与现有 E2E 套件。
 * 租户行存在但 {@code enabled=0} 时，{@link #tenantEnabled(Long)} 返回 false，
 * 建项目入口据此拒绝（而非悄悄落到错误的组织）。</p>
 *
 * <p><b>安全</b>：{@code orgName} 会被拼进 Gitee 请求路径（{@code /orgs/{org}/repos} 等），
 * 故 save 用保守正则强校验（字母/数字/-/_/.，长度 1–128），非法值一律拒绝。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeTenantConfigService {

    /** 合法 Gitee org login：字母/数字/-/_/.，长度 1–128。 */
    private static final Pattern ORG_PATTERN = Pattern.compile("^[A-Za-z0-9._-]{1,128}$");

    private final GiteeTenantConfigMapper mapper;
    private final RepoProviderSettings props;
    private final RepoProviderClient client;
    private final GiteeTokenService tokenService;

    /** 取某租户的单行配置（无则空）。 */
    private GiteeTenantConfig findByTenant(Long tenantId) {
        if (tenantId == null) {
            return null;
        }
        return mapper.selectOne(new LambdaQueryWrapper<GiteeTenantConfig>()
                .eq(GiteeTenantConfig::getTenantId, tenantId)
                .last("limit 1"));
    }

    /**
     * 「本租户自己提供了组织」的**唯一判据**。
     *
     * <p>{@link #effectiveOrg(Long)} 与视图里的 {@code source} 必须用同一个判据，
     * 否则会出现「{@code orgName} 是平台默认值、{@code source} 却写着 TENANT」这种
     * 自相矛盾的视图 —— 前端会据此显示「企业自配置」并指向一个共享组织。
     * 典型触发场景：租户行存在但 {@code enabled=0}（配置弹窗里关掉开关即可）。</p>
     */
    private boolean tenantSuppliesOrg(GiteeTenantConfig row) {
        return row != null
                && Boolean.TRUE.equals(row.getEnabled())
                && StringUtils.hasText(row.getOrgName());
    }

    /** 由给定行解析生效组织：本租户提供则用它，否则回落全局默认（永不为 null）。 */
    private String effectiveOrgOf(GiteeTenantConfig row) {
        return tenantSuppliesOrg(row) ? row.getOrgName() : props.getOrg();
    }

    /**
     * 解析某租户生效的 Gitee 组织。
     *
     * @return 租户已配置且 org 非空且可用（enabled=1）时返回其 org_name；否则回落全局默认（永不为 null）
     */
    public String effectiveOrg(Long tenantId) {
        // 全局默认（GiteeProperties.org 默认 ""，故此处永不为 null）
        return effectiveOrgOf(findByTenant(tenantId));
    }

    /** 是否真正配置了组织（生效 org 非空即视为已配置）。 */
    public boolean orgConfigured(Long tenantId) {
        return StringUtils.hasText(effectiveOrg(tenantId));
    }

    /**
     * 该租户是否启用 Gitee 仓库联动。
     *
     * @return 租户行存在且 enabled=0 → false；其余（含无行）→ true（继承平台默认行为）
     */
    public boolean tenantEnabled(Long tenantId) {
        return enabledOf(findByTenant(tenantId));
    }

    private boolean enabledOf(GiteeTenantConfig row) {
        // 无行 = 继承平台默认行为（视为启用）
        return row == null || Boolean.TRUE.equals(row.getEnabled());
    }

    /**
     * 该租户 Gitee 组织配置视图（供前端展示）。
     *
     * <p>返回字段（与前端契约一致）：tenantId / orgName(生效值) / source(TENANT|DEFAULT) /
     * configured(是否有本租户行) / enabled(tenantEnabled) / defaultOrg(平台默认) /
     * orgVerified / verifyMessage。GET 视图不携带操作人，故不做可见性探测（orgVerified=false）。</p>
     */
    public Map<String, Object> view(Long tenantId) {
        GiteeTenantConfig row = findByTenant(tenantId);
        return buildView(tenantId, row, null);
    }

    /**
     * 保存（upsert）某租户的组织配置。
     *
     * @param orgName     组织 login（强校验）
     * @param enabled     是否启用（空则默认 true）
     * @param actorUserId 操作人（用于审计与可见性探测）
     * @return 保存后的视图（含 best-effort 可见性探测结果）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> save(Long tenantId, String orgName, Boolean enabled, Long actorUserId) {
        if (tenantId == null) {
            throw BizException.badRequest("tenantId 不能为空");
        }
        String raw = orgName == null ? "" : orgName.trim();
        if (!ORG_PATTERN.matcher(raw).matches()) {
            throw BizException.badRequest(props.providerLabel() + " 组织名非法（仅允许字母/数字/-/_/.，长度 1–128）：" + raw);
        }
        Boolean effEnabled = enabled == null ? Boolean.TRUE : enabled;

        GiteeTenantConfig existing = findByTenant(tenantId);
        GiteeTenantConfig row = existing == null ? new GiteeTenantConfig() : existing;
        row.setTenantId(tenantId);
        row.setOrgName(raw);
        row.setEnabled(effEnabled);
        row.setUpdatedBy(actorUserId);
        if (existing == null) {
            row.setCreatedBy(actorUserId);
            // createdAt / updatedAt 由 AuditMetaObjectHandler 自动填充
            mapper.insert(row);
            log.info("已写入租户 Gitee 组织配置 tenant={} org={}", tenantId, raw);
        } else {
            mapper.updateById(row);
            log.info("已更新租户 Gitee 组织配置 tenant={} org={}", tenantId, raw);
        }
        return buildView(tenantId, row, actorUserId);
    }

    /**
     * 清除某租户的组织配置（删行，回落平台默认）。
     *
     * @return 清除后的视图
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> clear(Long tenantId) {
        GiteeTenantConfig row = findByTenant(tenantId);
        if (row != null) {
            mapper.deleteById(row.getId());
            log.info("已清除租户 Gitee 组织配置 tenant={}", tenantId);
        }
        return buildView(tenantId, null, null);
    }

    // ======================================================================
    // 视图组装 + best-effort 可见性探测
    // ======================================================================

    private Map<String, Object> buildView(Long tenantId, GiteeTenantConfig row, Long actorUserId) {
        String defaultOrg = props.getOrg();
        // 复用同一判据，避免「orgName 是默认值、source 却写 TENANT」的自相矛盾视图
        boolean supplies = tenantSuppliesOrg(row);
        String effective = effectiveOrgOf(row);
        boolean enabled = enabledOf(row);
        String source = supplies ? "TENANT" : "DEFAULT";

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("tenantId", tenantId);
        m.put("orgName", effective);
        m.put("source", source);
        // configured = 「本租户有自己的一行配置」（与 source 不同：enabled=0 的行仍算 configured，
        // 前端据此才敢显示「恢复平台默认」按钮）
        m.put("configured", row != null);
        m.put("enabled", enabled);
        m.put("defaultOrg", defaultOrg);
        Map<String, Object> probe = probeVisibility(tenantId, effective, actorUserId);
        m.put("orgVerified", probe.get("verified"));
        m.put("verifyMessage", probe.get("message"));
        return m;
    }

    /**
     * best-effort 组织可见性探测：若操作人已绑定 Gitee，调用 {@code GET /orgs/{org}} 确认其可见。
     *
     * <p><b>绝不阻塞保存</b>：探测失败（令牌失效 / 组织不可见 / Gitee 不可达）一律降级为
     * orgVerified=false 并给出中文说明；一个普通组织成员可能看不到组织、Gitee 不可达也不应
     * 阻止配置落地。捕获 {@link BizException}/{@link RepoProviderException}/一切异常。</p>
     */
    private Map<String, Object> probeVisibility(Long tenantId, String org, Long actorUserId) {
        Map<String, Object> r = new LinkedHashMap<>();
        if (!StringUtils.hasText(org)) {
            r.put("verified", false);
            r.put("message", "未配置组织，无需校验可见性");
            return r;
        }
        if (actorUserId == null) {
            r.put("verified", false);
            r.put("message", "未提供操作人，跳过组织可见性校验");
            return r;
        }
        try {
            GiteeAccount acc = tokenService.findAccount(tenantId, actorUserId);
            if (acc == null) {
                r.put("verified", false);
                r.put("message", "当前操作人未绑定 Gitee，跳过组织可见性校验");
                return r;
            }
            // 必要时自动续期；令牌失效会抛 BizException（被下方捕获）
            String token = tokenService.validToken(acc);
            client.getOrg(token, org);
            r.put("verified", true);
            r.put("message", "组织存在且当前账号可见");
            return r;
        } catch (BizException e) {
            // 令牌失效/未授权等：不算组织不可见，仅提示
            r.put("verified", false);
            r.put("message", "未校验（" + e.getMessage() + "）");
            return r;
        } catch (RepoProviderException e) {
            r.put("verified", false);
            r.put("message", "组织不可见或 " + props.providerLabel() + " 不可达：" + e.getMessage());
            return r;
        } catch (Exception e) {
            r.put("verified", false);
            r.put("message", "组织可见性校验失败：" + e.getMessage());
            return r;
        }
    }
}
