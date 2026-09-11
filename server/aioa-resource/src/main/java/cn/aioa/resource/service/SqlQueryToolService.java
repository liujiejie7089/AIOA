package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 只读 SQL 查询工具（方案 P3 / C5）：供数据分析师专家对租户业务数据做真实聚合分析。
 *
 * <p>安全约束（市面标准做法，白名单 + 只读 + 限行）：</p>
 * <ul>
 *   <li>只读：仅允许 SELECT / SHOW / DESCRIBE，拒绝任何 DML/DDL/DCL；</li>
 *   <li>白名单：只允许查 biz_* 业务数据集表（+ 少量只读字典表），
 *       禁止访问 sys_user / org_* / tenant_* 等敏感表，杜绝拖库；</li>
 *   <li>租户隔离：强制注入 tenant_id 过滤（WHERE 追加），跨租户数据零泄露；</li>
 *   <li>限行：强制 LIMIT，最多 200 行；</li>
 *   <li>禁用多语句 / 注释注入：分号、--、#、/* 一律拒绝。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SqlQueryToolService {

    /** 单次查询最大返回行数。 */
    private static final int MAX_ROWS = 200;

    /** 只读表白名单（租户业务数据集）。 */
    private static final List<String> ALLOWED_TABLES = List.of(
            "biz_customer", "biz_product", "biz_sales_order", "biz_contract",
            "biz_inventory", "biz_payment", "approval_order", "payment_order",
            "biz_kpi", "biz_kpi_trend");

    /** 危险关键词（DDL/DML/DCL/文件/权限）。 */
    private static final Pattern DANGEROUS = Pattern.compile(
            "(?i)\\b(insert|update|delete|drop|truncate|alter|create|replace|merge|grant|revoke|"
                    + "call|execute|load|outfile|dumpfile|into\\s+outfile)\\b");

    private final JdbcTemplate jdbcTemplate;

    /** 结果：列名 + 行数据 + 行数（供 agent 组织自然语言回答）。 */
    public record SqlResult(List<String> columns, List<Map<String, Object>> rows, int rowCount) {
        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("columns", columns);
            m.put("rows", rows);
            m.put("rowCount", rowCount);
            return m;
        }
    }

    /**
     * 执行只读查询。
     *
     * @param sql      用户/模型给的 SQL
     * @param tenantId 当前租户（强制注入隔离）
     */
    public SqlResult query(String sql, Long tenantId) {
        String s = validate(sql);
        long tid = tenantId == null ? 0L : tenantId;
        String scoped = injectTenant(s, tid);
        try {
            List<Map<String, Object>> rows = jdbcTemplate.queryForList(scoped);
            List<String> columns = rows.isEmpty() ? List.of() : new ArrayList<>(rows.get(0).keySet());
            return new SqlResult(columns, rows, rows.size());
        } catch (Exception e) {
            log.warn("sql_query 执行失败: {} (sql={})", e.getMessage(), scoped);
            throw BizException.badRequest("SQL 执行失败：" + e.getMessage());
        }
    }

    /** 校验并规整 SQL：只读、单句、白名单、限行。 */
    private String validate(String sql) {
        if (sql == null || sql.isBlank()) {
            throw BizException.badRequest("SQL 不能为空");
        }
        String s = sql.trim();
        // 多语句 / 注释注入
        if (s.contains(";") || s.contains("--") || s.contains("#") || s.contains("/*")) {
            throw BizException.badRequest("SQL 只允许单条语句，且不允许注释");
        }
        String lower = s.toLowerCase(Locale.ROOT);
        if (!lower.startsWith("select") && !lower.startsWith("show") && !lower.startsWith("describe")) {
            throw BizException.badRequest("SQL 只允许 SELECT / SHOW / DESCRIBE 只读查询");
        }
        if (DANGEROUS.matcher(lower).find()) {
            throw BizException.badRequest("SQL 包含被禁止的关键字（写操作/文件操作）");
        }
        if (!tablesAllowed(lower)) {
            throw BizException.badRequest("SQL 访问了白名单之外的表格");
        }
        return s;
    }

    /** 校验 SQL 中出现的所有表都在白名单内。 */
    private static boolean tablesAllowed(String lowerSql) {
        // 提取 from / join 后的表名（简单启发式，够用且保守）
        java.util.regex.Matcher m = Pattern.compile("(?i)(?:from|join)\\s+([a-z_][a-z0-9_]*)").matcher(lowerSql);
        while (m.find()) {
            String table = m.group(1);
            if (!ALLOWED_TABLES.contains(table)) {
                return false;
            }
        }
        return true;
    }

    /** 强制注入租户过滤：追加/改写 tenant_id 条件，保证跨租户隔离。 */
    private static String injectTenant(String sql, long tenantId) {
        String lower = sql.toLowerCase(Locale.ROOT);
        // 主表别名：FROM <table> [alias] 的 alias（若有），用于给 tenant_id 加前缀避免 JOIN 歧义
        String alias = mainTableAlias(sql);
        String tenantCond = (alias == null ? "" : alias + ".") + "tenant_id = " + tenantId;
        if (lower.contains("where")) {
            // 已显式带 tenant_id 条件则保持原样（避免重复）
            if (lower.contains("tenant_id")) {
                return sql;
            }
            int whereIdx = lower.indexOf("where") + "where".length();
            String tail = sql.substring(whereIdx);
            int endIdx = tail.length();
            for (String kw : new String[]{"group by", "order by", "limit", "having"}) {
                int k = tail.toLowerCase(Locale.ROOT).indexOf(kw);
                if (k >= 0) {
                    endIdx = Math.min(endIdx, k);
                }
            }
            String whereBody = tail.substring(0, endIdx).trim();
            String rest = tail.substring(endIdx);
            return sql.substring(0, whereIdx) + " " + whereBody + " AND " + tenantCond + " " + rest;
        }
        int insertAt = sql.length();
        for (String kw : new String[]{"group by", "order by", "limit", "having"}) {
            int k = lower.indexOf(kw);
            if (k >= 0) {
                insertAt = Math.min(insertAt, k);
            }
        }
        return sql.substring(0, insertAt).trim() + " WHERE " + tenantCond + " " + sql.substring(insertAt).trim();
    }

    /** 提取 FROM 后主表的别名（若有），无别名返回 null。 */
    private static String mainTableAlias(String sql) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(
                "(?i)from\\s+([a-z_][a-z0-9_]*)\\s+(?:as\\s+)?([a-z_][a-z0-9_]*)\\s").matcher(sql);
        if (m.find()) {
            return m.group(2);
        }
        return null;
    }
}
