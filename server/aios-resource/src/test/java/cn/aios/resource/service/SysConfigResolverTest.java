package cn.aios.resource.service;

import cn.aios.resource.entity.SysConfig;
import cn.aios.resource.entity.SysOrgConfig;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

/**
 * {@link SysConfigResolver#resolve} 纯函数核心单测 —— 不依赖 Spring / 数据库，
 * 读取经由注入的假 {@link SysConfigResolver.OrgLookup} / {@link SysConfigResolver.TenantLookup} 完成。
 *
 * <p>关注「回落链」三个关键点：机构覆盖优先、机构空白回落租户、机构为 null 直接读租户；
 * 外加两条边界：本租户无行回落平台默认、全无配置返回空串（绝不返回 null）。</p>
 */
class SysConfigResolverTest {

    /** 假机构查询：记录是否真的被查到，用来证明「跳过/不跳过机构层」的行为。 */
    private static final class FakeOrg implements SysConfigResolver.OrgLookup {
        final SysOrgConfig row;
        int calls = 0;

        FakeOrg(SysOrgConfig row) {
            this.row = row;
        }

        @Override
        public SysOrgConfig apply(Long tenantId, Long institutionId, String key) {
            calls++;
            return row;
        }
    }

    /** 假租户查询：按 tenantId 命中对应行（0 命中平台默认），无对应行返回 null。 */
    private static final class FakeTenant implements SysConfigResolver.TenantLookup {
        final List<SysConfig> rows;
        int calls = 0;

        FakeTenant(SysConfig... rows) {
            // 用 Arrays.asList：允许 null 元素（「无该行」用例需要传 null）
            this.rows = Arrays.asList(rows);
        }

        @Override
        public SysConfig apply(Long tenantId, String key) {
            calls++;
            for (SysConfig r : rows) {
                if (r != null && r.getTenantId() != null && r.getTenantId().equals(tenantId)) {
                    return r;
                }
            }
            return null;
        }
    }

    private static SysOrgConfig org(String value) {
        SysOrgConfig c = new SysOrgConfig();
        c.setConfigValue(value);
        return c;
    }

    private static SysConfig cfg(long tenantId, String value) {
        SysConfig c = new SysConfig();
        c.setTenantId(tenantId);
        c.setConfigValue(value);
        return c;
    }

    private static SysConfig cfgDefault(long tenantId, String value, String def) {
        SysConfig c = cfg(tenantId, value);
        c.setDefaultValue(def);
        return c;
    }

    @Test
    @DisplayName("机构覆盖优先：机构有非空覆盖值时，忽略租户/平台值")
    void institutionOverrideWins() {
        FakeOrg org = new FakeOrg(org("INST_VALUE"));
        FakeTenant tenant = new FakeTenant(cfg(5L, "TENANT_VALUE"), cfg(0L, "PLATFORM_VALUE"));

        String v = SysConfigResolver.resolve(5L, 7L, "k", org, tenant);

        assertEquals("INST_VALUE", v, "应返回机构覆盖值而非租户/平台值");
        assertEquals(1, org.calls, "机构层应被查询一次");
        assertEquals(0, tenant.calls, "机构命中后不应再回落租户层");
    }

    @Test
    @DisplayName("覆盖值为空白则回落租户：机构行存在但空白，必须落到租户值")
    void blankOverrideFallsBackToTenant() {
        // 机构行空白 ≠ 没有机构行：绝不能把空白当默认值，必须继续走租户层
        FakeOrg org = new FakeOrg(org("   "));
        FakeTenant tenant = new FakeTenant(cfg(5L, "TENANT_VALUE"), cfg(0L, "PLATFORM_VALUE"));

        String v = SysConfigResolver.resolve(5L, 7L, "k", org, tenant);

        assertEquals("TENANT_VALUE", v, "机构覆盖空白时应回落到租户值");
        assertEquals(1, org.calls);
        assertEquals(1, tenant.calls, "机构空白后应继续查租户层");
    }

    @Test
    @DisplayName("机构为 null 直接读租户：跳过机构层，命中本租户值")
    void nullInstitutionReadsTenantOnly() {
        FakeOrg org = new FakeOrg(org("SHOULD_NOT_BE_USED"));
        FakeTenant tenant = new FakeTenant(cfg(5L, "TENANT_VALUE"), cfg(0L, "PLATFORM_VALUE"));

        String v = SysConfigResolver.resolve(5L, null, "k", org, tenant);

        assertEquals("TENANT_VALUE", v, "机构为 null 时应直接读租户值");
        assertEquals(0, org.calls, "机构为 null 时机构层绝不应被查询");
    }

    @Test
    @DisplayName("机构为 null 且本租户无行 ⇒ 回落平台默认(tenant_id=0)")
    void nullInstitutionFallsBackToPlatform() {
        FakeOrg org = new FakeOrg(org("SHOULD_NOT_BE_USED"));
        FakeTenant tenant = new FakeTenant(null, cfg(0L, "PLATFORM_VALUE"));

        String v = SysConfigResolver.resolve(5L, null, "k", org, tenant);

        assertEquals("PLATFORM_VALUE", v);
        assertEquals(0, org.calls);
    }

    @Test
    @DisplayName("租户 config_value 空白但 defaultValue 非空 ⇒ 用 defaultValue 兜底")
    void blankTenantValueUsesDefaultValue() {
        FakeOrg org = new FakeOrg(org("   "));
        FakeTenant tenant = new FakeTenant(cfgDefault(5L, "   ", "FROM_DEFAULT"), cfg(0L, "PLATFORM_VALUE"));

        String v = SysConfigResolver.resolve(5L, 7L, "k", org, tenant);

        assertEquals("FROM_DEFAULT", v, "租户 config_value 空白时应回退到 defaultValue 列");
    }

    @Test
    @DisplayName("全无配置 ⇒ 返回空串，绝不返回 null")
    void noConfigReturnsEmptyString() {
        FakeOrg org = new FakeOrg(null);
        FakeTenant tenant = new FakeTenant(null, null);

        String v = SysConfigResolver.resolve(5L, 7L, "k", org, tenant);

        assertEquals("", v);
        assertFalse(v == null, "即使全无配置也必须返回空串而非 null");
    }
}
