package cn.aioa.integration.scfy.validate;

import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.contract.ScfyParam;
import cn.aioa.integration.scfy.core.ScfyEnums;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 参数校验器 —— 「AI 调用前校验参数」的落点。
 *
 * <p>与通常的参数校验不同，这里校验的<b>不是「合不合法」，而是「会不会静默出错」</b>。
 * scfy 有一类危险行为：<b>参数错了不报错，而是返回空结果或未过滤结果</b>。
 * 实测已确认两例：
 * <ul>
 *   <li>{@code area=甘孜藏族自治州}（文档给的全称）→ 返回 0 条，HTTP 200，code=0；</li>
 *   <li>{@code level=un} → 返回未过滤的全省数据，同样 200/0。</li>
 *   <li>{@code area=青羊区}（行政区划编码类参数传了名称）→ 返回全零，同样 200/0。</li>
 * </ul>
 * 这类错误如果放过，模型会把「查不到」当成事实回答用户，而真实原因是参数写错了 ——
 * <b>错误会伪装成结论</b>。所以本校验器宁可拦下并要求用户澄清，也不放行。</p>
 *
 * <p>校验顺序（先错先报，避免一次抛一堆让模型无从下手）：
 * 未知参数 → 必填缺失 → 枚举越界 → 类型/范围 → 静默失效预警。</p>
 */
public class ScfyParamValidator {

    /** 校验结果。 */
    public record Result(boolean ok,
                         Map<String, Object> normalized,
                         List<String> errors,
                         List<String> warnings,
                         String askUser) {

        public static Result ok(Map<String, Object> normalized, List<String> warnings) {
            return new Result(true, normalized, List.of(), warnings, null);
        }

        public static Result fail(List<String> errors, String askUser, List<String> warnings) {
            return new Result(false, Map.of(), errors, warnings, askUser);
        }
    }

    /**
     * 校验并归一化入参。
     *
     * @param endpoint 目标接口契约
     * @param raw      模型给出的原始入参（可能含 null 值、未知键、字符串化的数字）
     */
    public Result validate(ScfyEndpoint endpoint, Map<String, Object> raw) {
        Map<String, Object> in = raw == null ? Map.of() : raw;
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        Map<String, Object> normalized = new LinkedHashMap<>();

        // 1) 未知参数：模型臆造参数名（典型：照文档写 shopId，而契约是 id）。
        //    必须报错而不是忽略 —— 忽略会出现「参数传了但没生效」，结果与静默失效同类。
        for (String key : in.keySet()) {
            if (endpoint.param(key) == null) {
                ScfyParam correct = guessCorrectParam(endpoint, key);
                String hint = correct == null
                        ? "该接口没有这个参数。合法参数：" + paramList(endpoint)
                        : "该接口的正确参数名是 " + correct.name() + "（" + correct.description() + "）";
                errors.add("未知参数「" + key + "」：" + hint);
            }
        }

        // 2) 必填缺失 + 3) 枚举/类型/静默失效
        List<ScfyParam> missing = new ArrayList<>();
        for (ScfyParam p : endpoint.params()) {
            Object v = in.get(p.name());
            boolean absent = v == null || String.valueOf(v).isBlank();
            if (absent) {
                if (p.required()) {
                    missing.add(p);
                }
                continue;
            }
            String sv = String.valueOf(v).trim();

            // 枚举越界
            if (p.hasEnums() && !p.enums().contains(sv)) {
                errors.add("参数「" + p.name() + "」取值「" + sv + "」不在合法范围内。可选："
                        + String.join(" / ", p.enums()));
                continue;
            }

            // 类型与范围
            if ("integer".equals(p.type())) {
                Integer num = toInt(sv);
                if (num == null) {
                    errors.add("参数「" + p.name() + "」应为整数，实际是「" + sv + "」");
                    continue;
                }
                if ("pageSize".equals(p.name())) {
                    if (num < 1 || num > ScfyEnums.MAX_PAGE_SIZE) {
                        errors.add("参数「pageSize」应在 1~" + ScfyEnums.MAX_PAGE_SIZE + " 之间，实际 " + num);
                        continue;
                    }
                } else if (num < 1) {
                    errors.add("参数「" + p.name() + "」应 ≥ 1，实际 " + num);
                    continue;
                }
                normalized.put(p.name(), num);
                continue;
            }

            // 行政区划编码（areaCode）：这类参数传错不报错、只静默返回全零，
            // 所以必须按格式拦下 —— 否则「查不到」会被当成「这个地方没有非遗资源」回答用户。
            if ("areaCode".equals(p.type())) {
                if (!sv.matches("\\d{12}")) {
                    errors.add("参数「" + p.name() + "」应为 12 位行政区划编码（如 510105000000=青羊区、"
                            + "510100000000=成都市），实际是「" + sv + "」。"
                            + "传市州简称（如「青羊区」）或 6 位编码实测返回全零且不报错，故在此拦下；"
                            + "合法编码可从 tourist_county_list 接口取得（返回 id=编码、short_name=名称），"
                            + "不传则返回全省。");
                    continue;
                }
                normalized.put(p.name(), sv);
                continue;
            }

            normalized.put(p.name(), sv);
        }

        // 静默失效预警：不是错误，但必须让模型/用户知道「这个条件不会被采纳」
        if (normalized.containsKey("level") && !"country".equals(normalized.get("level"))) {
            warnings.add("level=" + normalized.get("level")
                    + " 实测不会生效（后端静默返回未过滤结果，不报错）。"
                    + "当前只有 level=country 真正能筛。");
        }

        if (!errors.isEmpty()) {
            return Result.fail(errors, null, warnings);
        }
        if (!missing.isEmpty()) {
            return Result.fail(List.of(), buildAskUser(endpoint, missing), warnings);
        }
        return Result.ok(normalized, warnings);
    }

    /**
     * 生成「参数不足时向用户追问」的话术。
     *
     * <p>三条原则（对应「不强行调用」）：
     * <ol>
     *   <li><b>说清要什么、为什么</b> —— 只报参数名（如 {@code area}）用户看不懂；</li>
     *   <li><b>给出可选项与示例</b> —— 有枚举就列出来，别让用户猜；</li>
     *   <li><b>不替用户默认</b> —— 不写「我按成都市查了」。</li>
     * </ol>
     */
    private String buildAskUser(ScfyEndpoint endpoint, List<ScfyParam> missing) {
        StringBuilder sb = new StringBuilder();
        sb.append("还需要以下信息才能查询「").append(endpoint.summary().replace("。", "")).append("」：\n");
        for (ScfyParam p : missing) {
            sb.append("· ").append(p.description());
            if (p.hasEnums()) {
                sb.append("（可选：").append(String.join(" / ", p.enums())).append("）");
            } else if (p.example() != null) {
                sb.append("（例如：").append(p.example()).append("）");
            }
            sb.append("\n");
        }
        sb.append("请补充后我再查询。");
        return sb.toString();
    }

    private static String paramList(ScfyEndpoint endpoint) {
        return endpoint.params().stream()
                .map(p -> p.name() + (p.required() ? "(必填)" : "(可选)"))
                .reduce((a, b) -> a + ", " + b).orElse("（无）");
    }

    /**
     * 猜「模型想传的其实是哪个参数」——专门对付照文档写错参数名的情形。
     * <p>文档写 {@code shopId}、契约是 {@code id}，两者没有字符包含关系，
     * 所以这里用「契约参数名是否是该 key 的子串」的粗略匹配给出提示，
     * 匹配不到就退回列出全部合法参数。</p>
     */
    private static ScfyParam guessCorrectParam(ScfyEndpoint endpoint, String wrongKey) {
        String k = wrongKey.toLowerCase();
        for (ScfyParam p : endpoint.params()) {
            String n = p.name().toLowerCase();
            if (k.contains(n) || n.contains(k)) {
                return p;
            }
        }
        // shopId → id 这类：去掉常见后缀再试
        for (String suffix : List.of("id", "code", "name")) {
            if (k.endsWith(suffix)) {
                String stem = k.substring(0, k.length() - suffix.length());
                for (ScfyParam p : endpoint.params()) {
                    String n = p.name().toLowerCase();
                    if (n.equals(suffix) || n.contains(stem)) {
                        return p;
                    }
                }
            }
        }
        return null;
    }

    private static Integer toInt(String s) {
        try {
            return Integer.valueOf(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
