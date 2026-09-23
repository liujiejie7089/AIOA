package cn.aioa.integration.scfy.agent;

import cn.aioa.integration.scfy.contract.ScfyParam;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 一个「已注册给 agent 的接口」的完整描述 —— 四条信息的载体。
 *
 * <p>这是本功能对外承诺的最小单元。任何一条缺失，模型就会出现一类可预期的失败：
 * <ul>
 *   <li>缺<b>名称</b> ⇒ 匹配到时无法向用户解释「我查了什么」；</li>
 *   <li>缺<b>用途描述</b> ⇒ 不知道该不该用它（这是语义匹配的主输入）；</li>
 *   <li>缺<b>参数</b> ⇒ 猜参数名，或漏传必填导致空结果（scfy 对错参数是静默返回空，不报错）；</li>
 *   <li>缺<b>返回结构</b> ⇒ 只能看到一大团 JSON，不知道取哪个字段，于是把整个响应体念给用户。</li>
 * </ul>
 * 所以这四项在 {@link ScfyAgentCatalog} 里是<b>构造时强制校验</b>的，不是「尽量填」。</p>
 *
 * @param toolCode    工具编码（{@code scfy_<endpointId>}），与 tool_definition 同源
 * @param endpointId  契约接口 id
 * @param group       能力域（传承人 / 项目 / 工坊 / 保护区 / 旅游）
 * @param name        展示名，来自 {@code @AioaTool(name=...)}
 * @param purpose     用途描述，来自 {@code @AioaTool(description=...)}，是语义匹配的主依据
 * @param path        真实接口路径，如 {@code /show/project/getProjectCountByArea}
 * @param params      参数契约（实测校正后），含必填性与枚举
 * @param inputSchema 模型可填的入参 JSON Schema（由 {@code @AioaToolParam} 推导）
 * @param outputSchema 返回结构 JSON Schema（统一信封 + 本接口 data 的实测形状）
 * @param dataShape   本接口 {@code data} 的实测形状（来自 return-shape.json）
 * @param observed    返回结构所依据的实测结论（{@code OK_DATA} 才算真实观测到）
 */
public record ScfyToolDescriptor(String toolCode,
                                 String endpointId,
                                 String group,
                                 String name,
                                 String purpose,
                                 String path,
                                 List<ScfyParam> params,
                                 Map<String, Object> inputSchema,
                                 Map<String, Object> outputSchema,
                                 Map<String, Object> dataShape,
                                 String observed) {

    /** 必填参数名。 */
    public List<String> requiredParams() {
        List<String> out = new ArrayList<>();
        for (ScfyParam p : params) {
            if (p.required()) {
                out.add(p.name());
            }
        }
        return out;
    }

    /** 可选参数名。 */
    public List<String> optionalParams() {
        List<String> out = new ArrayList<>();
        for (ScfyParam p : params) {
            if (!p.required()) {
                out.add(p.name());
            }
        }
        return out;
    }

    /** 是否观测到了真实数据（只有 {@code OK_DATA} 才算；调用成功但空集不算）。 */
    public boolean returnsData() {
        return "OK_DATA".equals(observed);
    }

    /** 返回结构是否可用（观测到了字段，或本身是标量）。 */
    @SuppressWarnings("unchecked")
    public boolean hasReturnStructure() {
        if (dataShape == null || dataShape.isEmpty()) {
            return false;
        }
        Object fields = dataShape.get("fields");
        if (fields instanceof Map<?, ?> m && !m.isEmpty()) {
            return true;
        }
        return dataShape.get("scalarKind") != null;
    }

    /** 四要素是否齐备：名称 / 用途 / 参数（声明即齐备，可能为空列表）/ 返回结构。 */
    public boolean isComplete() {
        return !blank(name) && !blank(purpose) && inputSchema != null && hasReturnStructure();
    }

    /**
     * 缺失的四要素里，哪些没齐 —— 启动自检用它生成可读报错。
     * 参数一项要求「注解推导出的 Schema 与契约参数同名同数」，避免两处漂移。
     */
    public List<String> missingParts() {
        List<String> miss = new ArrayList<>();
        if (blank(name)) {
            miss.add("名称（@AioaTool.name）");
        }
        if (blank(purpose)) {
            miss.add("用途描述（@AioaTool.description）");
        }
        if (inputSchema == null) {
            miss.add("参数（入参 Schema 缺失）");
        } else {
            Object props = inputSchema.get("properties");
            int schemaCount = props instanceof Map<?, ?> m ? m.size() : 0;
            if (schemaCount != params.size()) {
                miss.add("参数（注解 Schema 有 " + schemaCount + " 个，契约有 "
                        + params.size() + " 个：" + paramNames() + "）");
            }
        }
        if (!hasReturnStructure()) {
            miss.add("返回结构（return-shape.json 中没有本接口的实测形状，observed=" + observed + "）");
        }
        return miss;
    }

    private List<String> paramNames() {
        List<String> n = new ArrayList<>();
        for (ScfyParam p : params) {
            n.add(p.name());
        }
        return n;
    }

    /**
     * 供语义匹配使用的检索文本 —— 把「人可能怎么问」与「这个接口是什么」对齐。
     *
     * <p>刻意把<b>返回字段名也纳入</b>：用户常按结果字段提问（如「工坊的销售额」），
     * 而字段名只存在于返回结构里，不纳入就会漏配。</p>
     */
    public String searchText() {
        StringBuilder sb = new StringBuilder();
        sb.append(name).append(' ').append(purpose).append(' ').append(group).append(' ');
        for (ScfyParam p : params) {
            sb.append(p.name()).append(' ').append(p.description()).append(' ');
            if (p.hasEnums()) {
                sb.append(String.join(" ", p.enums())).append(' ');
            }
        }
        sb.append(shapeTokens(dataShape));
        return sb.toString();
    }

    /** 递归收集形状里的字段名（含嵌套数组元素字段），作为检索词。 */
    private static String shapeTokens(Map<String, Object> dataShape) {
        StringBuilder sb = new StringBuilder();
        if (dataShape != null) {
            collect(dataShape.get("fields"), sb, 3);
        }
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private static void collect(Object node, StringBuilder sb, int depth) {
        if (depth <= 0 || !(node instanceof Map<?, ?> m)) {
            return;
        }
        for (Map.Entry<?, ?> e : m.entrySet()) {
            sb.append(e.getKey()).append(' ');
            Object v = e.getValue();
            if (v instanceof Map<?, ?> nested) {
                collect(nested.get("fields"), sb, depth - 1);
            }
        }
    }

    /** 一行摘要，用于把候选列表回给模型。 */
    public String shortLine() {
        return toolCode + "｜" + group + "｜" + name + "：" + oneLine(purpose);
    }

    /** 返回结构的可读文本，如 {@code dataList[n]:{project_base_id, project_name}}。 */
    public String returnsText() {
        if (!hasReturnStructure()) {
            return "未观测到（observed=" + observed + "）";
        }
        String root = String.valueOf(dataShape.getOrDefault("dataKind", "object"));
        if ("scalar".equals(root)) {
            return "data:" + dataShape.get("scalarKind");
        }
        List<String> parts = new ArrayList<>();
        render(dataShape.get("fields"), parts, 2);
        String body = String.join(", ", parts);
        // 根就是数组时，字段其实属于元素，必须标明，否则模型会去找 data.<field>
        return "array".equals(root) ? "data[n]:{" + body + "}" : body;
    }

    @SuppressWarnings("unchecked")
    private static void render(Object fields, List<String> out, int depth) {
        if (depth <= 0 || !(fields instanceof Map<?, ?> m)) {
            return;
        }
        for (Map.Entry<?, ?> e : m.entrySet()) {
            Object v = e.getValue();
            if (v instanceof Map<?, ?> nested) {
                List<String> inner = new ArrayList<>();
                render(nested.get("fields"), inner, depth - 1);
                out.add(e.getKey() + ("array".equals(nested.get("kind")) ? "[n]" : "") + ":{"
                        + String.join(", ", inner) + "}");
            } else {
                out.add(e.getKey() + ":" + v);
            }
        }
    }

    private static String oneLine(String s) {
        if (s == null) {
            return "";
        }
        String t = s.replace('\n', ' ').replace('\r', ' ').replaceAll("\\s+", " ").trim();
        return t.length() > 90 ? t.substring(0, 90) + "…" : t;
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }

    /** 便于测试与展示：把四要素压成 Map。 */
    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("toolCode", toolCode);
        m.put("endpoint", endpointId);
        m.put("group", group);
        m.put("name", name);
        m.put("purpose", purpose);
        m.put("path", path);
        m.put("params", params);
        m.put("inputSchema", inputSchema);
        m.put("returns", returnsText());
        m.put("outputSchema", outputSchema);
        m.put("observed", observed);
        return m;
    }
}
