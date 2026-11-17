package cn.aios.resource.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * SQL 工具租户隔离（H1）：无论 SQL 自身是否提到 tenant_id，都必须追加当前租户条件。
 *
 * <p>旧逻辑「SQL 文本含 tenant_id 就原样放行」可被 {@code WHERE tenant_id>0} 绕过，
 * 造成跨租户拖库。这里用反射直接调 private injectTenant，钉死字符串形态的判据。</p>
 */
class SqlQueryToolTenantTest {

    private static String inject(String sql, long tenantId) throws Exception {
        Method m = SqlQueryToolService.class.getDeclaredMethod("injectTenant", String.class, long.class);
        m.setAccessible(true);
        return (String) m.invoke(null, sql, tenantId);
    }

    @Test
    @DisplayName("SQL 自带 tenant_id>0 也必须叠加当前租户条件")
    void forcesTenantEvenWhenSqlMentionsIt() throws Exception {
        String out = inject("SELECT * FROM biz_sales_order WHERE tenant_id > 0", 42L);
        assertTrue(out.contains("tenant_id = 42"), out);
        assertTrue(out.contains("tenant_id > 0"), out);  // 原条件保留，只会更窄
    }

    @Test
    @DisplayName("无 WHERE 时追加 WHERE tenant_id")
    void appendsWhereWhenAbsent() throws Exception {
        String out = inject("SELECT * FROM biz_customer", 7L);
        assertTrue(out.contains("WHERE tenant_id = 7"), out);
    }

    @Test
    @DisplayName("有 WHERE + ORDER BY 时把租户条件插在 ORDER BY 之前")
    void insertsBeforeOrderBy() throws Exception {
        String out = inject("SELECT * FROM biz_customer WHERE status='A' ORDER BY id LIMIT 10", 9L);
        assertTrue(out.contains("status='A' AND tenant_id = 9"), out);
        assertTrue(out.indexOf("tenant_id = 9") < out.indexOf("ORDER BY"), out);
    }

    @Test
    @DisplayName("别名主表用别名前缀，避免 JOIN 时 tenant_id 歧义")
    void prefixAlias() throws Exception {
        String out = inject("SELECT * FROM biz_customer c WHERE c.status='A'", 3L);
        assertTrue(out.contains("c.tenant_id = 3"), out);
    }
}
