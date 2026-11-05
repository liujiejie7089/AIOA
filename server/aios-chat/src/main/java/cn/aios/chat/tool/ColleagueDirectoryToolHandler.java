package cn.aios.chat.tool;

import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 「查同事」工具（2026-11-05）。
 *
 * <p>解决的是「数字人不知道这家公司里有谁」：用户说「共享给老王」，模型只能瞎猜一个 userId，
 * 或者干脆让用户自己去页面点。有了这个工具，模型可以先查再问、也能在回答里说清同事的部门与职务。</p>
 *
 * <p><b>字段口径（有意收窄）</b>：只回 姓名 / 部门 / 职务 / 工号。
 * 手机号、邮箱**不返回** —— 「能查到这个人」和「拿到他的联系方式」是两件事，
 * 后者应当走通讯录权限，而不是顺手塞进模型上下文（那里会被写进日志、历史与会话快照）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ColleagueDirectoryToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "list_colleagues";

    /** 单次返回上限：够模型认人，又不至于把整个通讯录灌进上下文。 */
    private static final int LIMIT = 30;

    private final JdbcTemplate jdbc;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "按姓名/部门/职务关键词查询本企业的同事（只返回姓名、部门、职务、工号，不含手机号与邮箱）。"
                + "用户提到某位同事但没给账号、或需要确认「我们公司有没有这个人」「他在哪个部门」时调用。"
                + "关键词为空则列出前若干位同事。查不到就如实说没有这个人，不要编造姓名。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"keyword\":{\"type\":\"string\",\"description\":\"姓名/部门/职务的模糊关键词，可留空\"}"
                + "},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        String kw = args == null || args.get("keyword") == null ? "" : String.valueOf(args.get("keyword")).trim();
        Long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        try {
            List<Object> params = new ArrayList<>();
            StringBuilder sql = new StringBuilder(
                    "SELECT m.user_id, m.name, m.job_title, m.employee_no, d.name AS dept_name "
                            + "FROM org_member m LEFT JOIN org_department d ON d.id = m.department_id "
                            + "WHERE m.tenant_id = ? AND m.status = 'ACTIVE' AND m.deleted_at IS NULL ");
            params.add(tenantId);
            if (!kw.isEmpty()) {
                sql.append("AND (m.name LIKE ? OR m.job_title LIKE ? OR d.name LIKE ?) ");
                String like = "%" + kw + "%";
                params.add(like);
                params.add(like);
                params.add(like);
            }
            sql.append("ORDER BY m.name LIMIT ").append(LIMIT);
            List<Map<String, Object>> rows = jdbc.queryForList(sql.toString(), params.toArray());

            List<Map<String, Object>> people = new ArrayList<>();
            for (Map<String, Object> r : rows) {
                Map<String, Object> p = new LinkedHashMap<>();
                p.put("userId", r.get("user_id"));
                p.put("name", r.get("name"));
                p.put("department", r.get("dept_name"));
                p.put("jobTitle", r.get("job_title"));
                p.put("employeeNo", r.get("employee_no"));
                people.add(p);
            }
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("keyword", kw);
            data.put("count", people.size());
            data.put("people", people);
            data.put("truncated", people.size() >= LIMIT);
            data.put("note", people.isEmpty()
                    ? "没有匹配的同事（可能不在企业组织架构里，或姓名写法不同）"
                    : "共 " + people.size() + " 位；不含手机号与邮箱，需要联系方式请走通讯录");
            return Map.of("ok", true, "data", data);
        } catch (Exception e) {
            log.warn("list_colleagues failed: {}", e.getMessage());
            return Map.of("ok", false, "error", "查询同事失败：" + e.getMessage());
        }
    }
}
