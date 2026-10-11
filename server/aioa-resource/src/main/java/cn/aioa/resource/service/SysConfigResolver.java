package cn.aioa.resource.service;

import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.entity.SysOrgConfig;
import cn.aioa.resource.mapper.SysConfigMapper;
import cn.aioa.resource.mapper.SysOrgConfigMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 系统参数「有效值」的<b>唯一解析入口</b>（需求二收尾，docs/44 §2.5 B 案）。
 *
 * <p><b>唯一解析入口</b>：机构覆盖值 → 租户值 → 平台默认（tenant_id=0）→ 空串。
 * 任何新的配置读取点（用户端配置、默认 AI、机构参数页……）一律走 {@link #effectiveValue}，
 * <b>不得再复制一份回落链</b> —— 复制就会再次分裂出「两份口径」（铁律 #1），
 * 这是此前 {@code ConfigController.resolve} 私有的根因。</p>
 *
 * <p><b>零回归性质</b>：当 {@code sys_org_config} 里没有任何该机构、该键的覆盖行时，
 * 机构覆盖层整段跳过，行为与该逻辑引入前<b>逐字节一致</b>
 * （仍按「租户值 → 平台默认 → 空串」回落）。机构覆盖层是纯增量，不影响任何既有读取路径。</p>
 *
 * <p><b>为什么必须回落到 tenant_id=0</b>：{@code sys_config} 只在租户<b>首次访问</b>管理端时才克隆平台默认，
 * 因此新增的键在老租户里根本没有行；不回落到 tenant_id=0 就会「管理端配了、用户端看不到」。</p>
 *
 * <p><b>可测试性</b>：真正的算法在静态纯函数 {@link #resolve} 里，读取经由 {@link OrgLookup}/{@link TenantLookup}
 * 两个可注入的函数接口传入，因此单测可以用假查询验证而不依赖 Spring / 数据库。</p>
 */
@Service
@RequiredArgsConstructor
public class SysConfigResolver {

    private final SysConfigMapper configMapper;
    private final SysOrgConfigMapper orgConfigMapper;

    /**
     * 解析某参数的有效值。
     *
     * @param tenantId      租户 ID（一律来自登录态，不接受前端入参）
     * @param institutionId 机构 ID；为 null 时跳过机构覆盖层（如平台/租户管理员未指定机构、或用户未绑定机构）
     * @param key           参数键
     * @return 有效值字符串；全无配置时返回空串（""），不返回 null
     */
    public String effectiveValue(Long tenantId, Long institutionId, String key) {
        return resolve(tenantId, institutionId, key, this::orgRow, this::tenantRow);
    }

    /**
     * 纯函数核心：把「机构覆盖 → 租户值 → 平台默认 → 空串」的算法与具体数据源解耦，
     * 读取经由 {@code orgLookup} / {@code tenantLookup} 注入。单测据此注入假查询。
     *
     * <p>空串覆盖值必须跳过、不得遮蔽租户值：机构覆盖行若存在但值为空白，按「未配」处理，
     * 继续回落到租户/平台值（避免「配了空串反而盖掉正常值」）。</p>
     */
    static String resolve(Long tenantId, Long institutionId, String key,
                         OrgLookup orgLookup, TenantLookup tenantLookup) {
        if (institutionId != null) {
            SysOrgConfig orgRow = orgLookup.apply(tenantId, institutionId, key);
            if (orgRow != null) {
                String ov = orgRow.getConfigValue();
                if (ov != null && !ov.isBlank()) {
                    return ov;
                }
            }
        }
        for (Long scope : List.of(tenantId, 0L)) {
            SysConfig row = tenantLookup.apply(scope, key);
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

    /** 机构覆盖行查询（可注入，便于单测）。 */
    @FunctionalInterface
    public interface OrgLookup {
        SysOrgConfig apply(Long tenantId, Long institutionId, String key);
    }

    /** 租户/平台参数行查询（可注入，便于单测）。 */
    @FunctionalInterface
    public interface TenantLookup {
        SysConfig apply(Long tenantId, String key);
    }

    private SysOrgConfig orgRow(Long tenantId, Long institutionId, String key) {
        return orgConfigMapper.selectOne(new LambdaQueryWrapper<SysOrgConfig>()
                .eq(SysOrgConfig::getTenantId, tenantId)
                .eq(SysOrgConfig::getInstitutionId, institutionId)
                .eq(SysOrgConfig::getConfigKey, key)
                .last("LIMIT 1"));
    }

    private SysConfig tenantRow(Long tenantId, String key) {
        return configMapper.selectOne(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, tenantId)
                .eq(SysConfig::getConfigKey, key)
                .last("LIMIT 1"));
    }
}
