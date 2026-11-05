package cn.aios.chat.tool;

import cn.aios.org.entity.ApprovalFlowDef;
import cn.aios.org.entity.ApprovalTask;
import cn.aios.org.service.ApprovalFlowService;
import cn.aios.org.support.OrgGuard;
import cn.aios.security.AuthUser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 审批流配置工具的公共部分（2026-11-05）。
 *
 * <p>三个工具（list / get / update）共用同一套口径，抽到这里而不是各写一遍：
 * 谁能改、节点长什么样、节点怎么用中文说清楚、参数缺什么该怎么问。</p>
 *
 * <p><b>为什么把「参数够了才配置」放在服务端</b>：模型很擅长"看起来懂了"——
 * 用户说「把请假的第二级改成部门负责人」，它可能直接提交一份只含一个节点的配置，
 * 把原来两级流程改坏。把校验做成**返回 missing 清单**而不是抛异常，
 * 模型就能照着清单继续问，而不会瞎猜一个值填进去。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ApprovalFlowToolSupport {

    /** 允许改流程配置的角色：租户管理员（全租户）与企业管理员（本机构）。 */
    static final Set<String> CONFIG_ROLES = Set.of(
            OrgGuard.ROLE_ADMIN, OrgGuard.ROLE_TENANT_ADMIN, OrgGuard.ROLE_ORG_ADMIN);

    /** 合法审批人类型 → 中文名（与 ApprovalTask 常量一一对应）。 */
    static final Map<String, String> APPROVER_LABELS = new LinkedHashMap<>() {{
        put(ApprovalTask.TYPE_DEPT_LEADER, "部门负责人");
        put(ApprovalTask.TYPE_ORG_ADMIN, "企业管理员");
        put(ApprovalTask.TYPE_TENANT_ADMIN, "租户管理员");
        put(ApprovalTask.TYPE_PLATFORM_ADMIN, "平台管理员");
        put(ApprovalTask.TYPE_SPECIFIC, "指定人员");
        put(ApprovalTask.TYPE_APPLICANT_SUPERIOR, "申请人的上级");
        put(ApprovalTask.TYPE_DEPT_DUTY, "部门值班岗");
        put(ApprovalTask.TYPE_UNIT_DUTY, "单位值班岗");
    }};

    static final Map<String, String> MODE_LABELS = Map.of(
            ApprovalTask.MODE_SINGLE, "依次审批（一人审完）",
            ApprovalTask.MODE_PARALLEL, "会签（全部同意才过）",
            ApprovalTask.MODE_GRAB, "抢办（一人处理即可）");

    private static final ObjectMapper M = new ObjectMapper();

    private final ApprovalFlowService flowService;
    private final JdbcTemplate jdbc;

    /** 有没有配置审批流的资格；没有就返回一句人话，调用方直接把它当工具结果回给模型。 */
    String permissionProblem(AuthUser user) {
        if (user == null) {
            return "当前没有登录用户，无法修改审批流配置";
        }
        List<String> roles = user.getRoles() == null ? List.of() : user.getRoles();
        for (String r : roles) {
            if (CONFIG_ROLES.contains(r)) {
                return null;
            }
        }
        return "只有租户管理员或企业管理员可以修改审批流配置，你当前的角色不允许。"
                + "可以让管理员在「审批流配置」里修改，或先申请相应角色。";
    }

    List<ApprovalFlowDef> defs(AuthUser user, Long institutionId) {
        return flowService.listDefs(tenantOf(user), institutionId);
    }

    ApprovalFlowDef defById(AuthUser user, Long id) {
        if (id == null) {
            return null;
        }
        for (ApprovalFlowDef d : defs(user, null)) {
            if (d.getId().equals(id)) {
                return d;
            }
        }
        return null;
    }

    /** 机构清单（用于「改哪个机构的流程」这一问）。只回 id/name，别的一概不带。 */
    List<Map<String, Object>> institutions(AuthUser user) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, name FROM org_institution WHERE tenant_id = ? AND deleted_at IS NULL "
                        + "ORDER BY id", tenantOf(user));
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            out.add(new LinkedHashMap<>(r));
        }
        return out;
    }

    String institutionName(Long id) {
        if (id == null || id == 0) {
            return "全租户（未绑定机构）";
        }
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT name FROM org_institution WHERE id = ?", id);
        return rows.isEmpty() ? ("机构#" + id) : String.valueOf(rows.get(0).get("name"));
    }

    /** 把一个定义压成「给模型看的一行」：id 名称 业务类型 机构 状态 级数。 */
    Map<String, Object> brief(ApprovalFlowDef d) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("defId", d.getId());
        m.put("name", d.getName());
        m.put("bizType", d.getBizType());
        m.put("institutionId", d.getInstitutionId());
        m.put("institution", institutionName(d.getInstitutionId()));
        m.put("status", d.getStatus());
        List<Map<String, Object>> steps = parseSteps(d.getStepsJson());
        m.put("stepCount", steps.size());
        m.put("stepsText", describeSteps(steps));
        return m;
    }

    /** 完整配置：节点明细 + 最近版本号（改之前先看版本，改之后能回溯）。 */
    Map<String, Object> detail(ApprovalFlowDef d) {
        Map<String, Object> m = new LinkedHashMap<>(brief(d));
        m.put("steps", parseSteps(d.getStepsJson()));
        m.put("remark", d.getRemark());
        m.put("updatedAt", d.getUpdatedAt() == null ? null : d.getUpdatedAt().toString());
        try {
            List<Map<String, Object>> vs = flowService.listDefVersions(d.getId(), d.getTenantId());
            m.put("latestVersion", vs.isEmpty() ? 0 : vs.get(vs.size() - 1).get("version"));
            m.put("versionCount", vs.size());
        } catch (RuntimeException e) {
            m.put("latestVersion", null);
        }
        return m;
    }

    List<Map<String, Object>> parseSteps(String json) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (json == null || json.isBlank()) {
            return out;
        }
        try {
            JsonNode arr = M.readTree(json);
            if (!arr.isArray()) {
                return out;
            }
            for (JsonNode n : arr) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = M.convertValue(n, Map.class);
                out.add(m);
            }
        } catch (Exception e) {
            log.warn("解析审批流 steps 失败：{}", e.getMessage());
        }
        return out;
    }

    /** 中文串：第1级 部门负责人 → 第2级 企业管理员（抄送 企业管理员）。 */
    String describeSteps(List<Map<String, Object>> steps) {
        if (steps.isEmpty()) {
            return "（未配置节点，运行期按单节点「企业管理员」兜底）";
        }
        StringBuilder sb = new StringBuilder();
        int i = 0;
        for (Map<String, Object> s : steps) {
            i++;
            String type = str(s.get("approver_type"), str(s.get("approverType"), ""));
            String label = APPROVER_LABELS.getOrDefault(type, type.isBlank() ? "未指定" : type);
            if (sb.length() > 0) {
                sb.append(" → ");
            }
            sb.append("第").append(i).append("级 ").append(label);
            Object mode = s.get("mode");
            if (mode != null && !String.valueOf(mode).isBlank()) {
                sb.append("[").append(MODE_LABELS.getOrDefault(String.valueOf(mode), String.valueOf(mode))).append("]");
            }
            Object th = s.get("threshold_days");
            if (th != null && !String.valueOf(th).isBlank()) {
                sb.append("(≥").append(th).append("天时启用)");
            }
            Object cc = s.get("cc");
            if (cc instanceof List<?> list && !list.isEmpty()) {
                sb.append("，抄送").append(list.size()).append("类");
            }
        }
        return sb.toString();
    }

    /**
     * 校验节点数组，返回问题清单（空 = 通过）。
     *
     * <p>与 {@code ApprovalFlowService.validateSteps} 的区别：那边只挡"结构不合法"并抛异常，
     * 这里是给模型看的**可行动提示**（第几级、缺什么、可选项有哪些），返回而不抛。</p>
     */
    List<String> problems(Object steps) {
        List<String> out = new ArrayList<>();
        if (!(steps instanceof List<?> list) || list.isEmpty()) {
            out.add("steps 必须是非空数组：每个元素是一级审批节点");
            return out;
        }
        int i = 0;
        for (Object o : list) {
            i++;
            if (!(o instanceof Map<?, ?> raw)) {
                out.add("第 " + i + " 级必须是对象");
                continue;
            }
            Map<?, ?> node = raw;
            String type = str(node.get("approver_type"), str(node.get("approverType"), ""));
            if (type.isBlank()) {
                out.add("第 " + i + " 级缺 approver_type（可选：" + String.join(" / ", APPROVER_LABELS.keySet()) + "）");
            } else if (!APPROVER_LABELS.containsKey(type)) {
                out.add("第 " + i + " 级的 approver_type「" + type + "」不认识（可选："
                        + String.join(" / ", APPROVER_LABELS.keySet()) + "）");
            } else if (ApprovalTask.TYPE_SPECIFIC.equals(type) && node.get("approver_id") == null
                    && node.get("approverId") == null) {
                out.add("第 " + i + " 级是 SPECIFIC（指定人员），必须给 approver_id");
            }
            Object mode = node.get("mode");
            if (mode != null && !String.valueOf(mode).isBlank()
                    && !MODE_LABELS.containsKey(String.valueOf(mode))) {
                out.add("第 " + i + " 级的 mode「" + mode + "」不支持（可选：single / parallel / grab）");
            }
            Object th = node.get("threshold_days");
            if (th != null && !String.valueOf(th).isBlank()) {
                try {
                    if (Integer.parseInt(String.valueOf(th).trim()) < 0) {
                        out.add("第 " + i + " 级的 threshold_days 不能是负数");
                    }
                } catch (NumberFormatException e) {
                    out.add("第 " + i + " 级的 threshold_days 必须是整数");
                }
            }
            Object when = node.get("when");
            if (when != null && (!(when instanceof Map<?, ?> w) || w.get("field") == null)) {
                out.add("第 " + i + " 级的 when 必须是含 field 的对象，如 {\"field\":\"days\",\"op\":\"<=\",\"value\":3}");
            }
            Object cc = node.get("cc");
            if (cc != null && !(cc instanceof List<?>)) {
                out.add("第 " + i + " 级的 cc 必须是数组");
            }
        }
        return out;
    }

    long tenantOf(AuthUser user) {
        return user.getTenantId() == null ? 0L : user.getTenantId();
    }

    static String str(Object a, String alt) {
        String v = a == null ? "" : String.valueOf(a).trim();
        return v.isBlank() ? alt : v;
    }
}
