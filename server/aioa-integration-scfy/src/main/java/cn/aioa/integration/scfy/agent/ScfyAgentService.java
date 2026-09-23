package cn.aioa.integration.scfy.agent;

import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.contract.ScfyParam;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import cn.aioa.tool.sdk.LocalToolRegistry;
import cn.aioa.tool.sdk.ToolCallContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 端到端问答入口：<b>自然语言提问 → 语义匹配 → 抽取参数 → 自动调用 → 返回数据</b>。
 *
 * <p><b>为什么选工具要分两段（先按描述排、再按能不能凑齐必填参数筛）</b>：
 * 只用描述排序，会遇到「描述最像但参数凑不齐」的接口 —— 比如用户问
 * 「成都有哪些非遗工坊」，描述最像的是 {@code shop_detail}，
 * 但它必填 {@code cityName + id}，而提问里没有 id；此时硬调只会得到一句追问话术，
 * 而同一句话用 {@code shop_table}（只要 cityName）就能直接把工坊列表拿出来，
 * 列表里的 {@code list[].id} 才正是下一次查详情要用的输入。
 * 反过来只按「参数好凑」排序，会挑到描述不相关的简单接口。
 * 所以：<b>描述决定候选顺序，参数可满足性只用来在头部窗口里挑能一把调通的</b>，
 * 且不越过「描述必须达到匹配阈值」这道门。</p>
 *
 * <p>匹配不到时如实返回 {@code matched=false} 与候选清单，不猜一个接口去调 ——
 * 猜错的代价是一份看起来正常、实际答非所问的数据，比「我不知道」有害得多。</p>
 */
public class ScfyAgentService {

    private static final Logger log = LoggerFactory.getLogger(ScfyAgentService.class);

    /** 参与「参数可满足性」复选的候选数（只在头部几条里挑，避免把弱相关接口捞上来）。 */
    private static final int RERANK_WINDOW = 3;

    private final ToolMatcher matcher;
    private final ScfyParamExtractor extractor;
    private final LocalToolRegistry registry;
    private final ScfyParamValidator validator;
    private final ObjectMapper mapper;
    /** 直接注入注册表（测试用）；为 null 时按需从 registry 装配。 */
    private final ScfyAgentCatalog pinnedCatalog;
    private volatile ScfyAgentCatalog catalogCache;

    public ScfyAgentService(LocalToolRegistry registry,
                            ObjectMapper mapper,
                            ToolMatcher matcher,
                            ScfyParamExtractor extractor,
                            ScfyParamValidator validator) {
        this.registry = registry;
        this.mapper = mapper;
        this.matcher = matcher;
        this.extractor = extractor;
        this.validator = validator;
        this.pinnedCatalog = null;
    }

    /** 直接用现成注册表构造（测试与离线装配用）。 */
    public ScfyAgentService(ScfyAgentCatalog catalog,
                            ToolMatcher matcher,
                            ScfyParamExtractor extractor,
                            LocalToolRegistry registry,
                            ScfyParamValidator validator) {
        this.registry = registry;
        this.mapper = null;
        this.matcher = matcher;
        this.extractor = extractor;
        this.validator = validator;
        this.pinnedCatalog = catalog;
        this.catalogCache = catalog;
    }

    /**
     * 注册表按需装配。
     *
     * <p><b>为什么不是启动时就装配</b>：工具是 {@code @AioaTool} 注解，由 SDK 的扫描器在
     * 「所有单例实例化完成之后」才写进 {@code LocalToolRegistry}。若在 Bean 创建阶段就读注册表，
     * 会读到一张空表 —— 表现为「注册表为空」而不是报错，最难查。按需装配绕开了这个时序陷阱：
     * 第一次真正要用时（用户提问 / 就绪自检），扫描必然已经完成。</p>
     */
    public ScfyAgentCatalog catalog() {
        ScfyAgentCatalog c = catalogCache;
        if (c == null) {
            synchronized (this) {
                c = catalogCache;
                if (c == null) {
                    c = pinnedCatalog != null ? pinnedCatalog
                            : ScfyAgentCatalog.load(registry, mapper);
                    catalogCache = c;
                }
            }
        }
        return c;
    }

    public ToolMatcher matcher() {
        return matcher;
    }

    // ==================== 主流程 ====================

    /** 自然语言提问 → 自动匹配并调用。 */
    public Map<String, Object> ask(String question) {
        return ask(question, null);
    }

    /**
     * 自然语言提问 → 自动匹配并调用。
     *
     * @param question 用户原话
     * @param toolCode 指定工具时跳过匹配（编排层已经决定用哪个接口时使用）；为 null 则自动匹配
     */
    public Map<String, Object> ask(String question, String toolCode) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("question", question);
        out.put("matcher", matcher.name());

        if (question == null || question.isBlank()) {
            out.put("ok", false);
            out.put("matched", false);
            out.put("errors", List.of("问题为空：请给出要查询的非遗问题，例如「成都有哪些非遗工坊」。"));
            return out;
        }

        ScfyToolDescriptor tool;
        List<ToolMatcher.Match> ranked;
        if (toolCode != null && !toolCode.isBlank()) {
            tool = resolvePinned(toolCode, out);
            if (tool == null) {
                return out;
            }
            ranked = List.of();
            out.put("matchedBy", "指定工具");
        } else {
            ranked = matcher.rank(question, catalog().registered(), 5);
            out.put("candidates", ranked.stream().map(ToolMatcher.Match::line).toList());
            if (ranked.isEmpty() || ranked.get(0).score() < matcher.minScore()) {
                out.put("ok", false);
                out.put("matched", false);
                out.put("errors", List.of(noMatchHint(ranked)));
                return out;
            }
            tool = pick(question, ranked);
            out.put("matchedBy", "语义匹配(" + matcher.name() + ")");
        }

        ScfyParamExtractor.Extraction ex = extractor.extract(question, tool);
        out.put("tool", tool.toolCode());
        out.put("toolName", tool.name());
        out.put("purpose", tool.purpose());
        out.put("endpoint", tool.endpointId());
        out.put("score", scoreOf(tool, ranked));
        out.put("matchReasons", reasonsOf(tool, ranked));
        out.put("args", ex.args());
        out.put("argEvidence", ex.evidence());
        out.put("returns", tool.returnsText());

        // 调用前先自己校验一遍参数。
        // 为什么不能指望工具内部那次校验：工具网关的绑定器在「缺必填参数」时会
        // 直接抛 IllegalArgumentException（信息只有「缺少必填参数：xxx」），
        // 根本进不到工具方法里，也就拿不到校验器生成好的追问话术。
        // 前置校验用的是同一个校验器实例，判定与话术与实际下发完全一致。
        ScfyEndpoint ep = ScfyCatalog.byId(tool.endpointId());
        ScfyParamValidator.Result vr = validator.validate(ep, ex.args());
        if (!vr.ok()) {
            out.put("ok", false);
            out.put("preflightFailure", true);
            out.put("errors", vr.errors());
            if (vr.askUser() != null) {
                out.put("needUserInput", true);
                out.put("askUser", vr.askUser());
            }
            if (!vr.warnings().isEmpty()) {
                out.put("warnings", vr.warnings());
            }
            return out;
        }

        Map<String, Object> payload = invoke(tool, vr.normalized(), out);
        if (payload == null) {
            return out;
        }

        out.put("ok", payload.get("ok"));
        out.put("data", payload.get("data"));
        copyIfPresent(payload, out, "errors");
        copyIfPresent(payload, out, "warnings");
        copyIfPresent(payload, out, "docMismatch");
        copyIfPresent(payload, out, "truncated");
        copyIfPresent(payload, out, "truncatedField");
        copyIfPresent(payload, out, "totalItems");
        copyIfPresent(payload, out, "returnedItems");
        copyIfPresent(payload, out, "elapsedMs");
        copyIfPresent(payload, out, "needUserInput");
        copyIfPresent(payload, out, "askUser");
        return out;
    }

    /** 指定工具时的校验：必须存在、且参与自动匹配（即已实测有数据）。 */
    private ScfyToolDescriptor resolvePinned(String toolCode, Map<String, Object> out) {
        ScfyToolDescriptor d = catalog().byToolCode(toolCode);
        if (d == null) {
            out.put("ok", false);
            out.put("matched", false);
            out.put("errors", List.of("没有这个工具：" + toolCode + "。可用工具清单见 scfy_catalog。"));
            return null;
        }
        if (!d.returnsData()) {
            out.put("ok", false);
            out.put("matched", false);
            out.put("errors", List.of("工具 " + toolCode + " 实测不返回数据（observed=" + d.observed()
                    + "），已排除在自动调用之外。"));
            return null;
        }
        return d;
    }

    /**
     * 在匹配头部里挑一个「必填参数能被提问满足」的接口。
     * <p>找不到就回落为第一名 —— 由校验器生成追问话术，让用户补信息，
     * 这比自动换一个语义不够贴合、但能调通的接口更诚实。</p>
     */
    private ScfyToolDescriptor pick(String question, List<ToolMatcher.Match> ranked) {
        List<ToolMatcher.Match> window = ranked.size() > RERANK_WINDOW
                ? ranked.subList(0, RERANK_WINDOW) : ranked;
        for (ToolMatcher.Match m : window) {
            ScfyParamExtractor.Extraction ex = extractor.extract(question, m.tool());
            if (ex.args().keySet().containsAll(m.tool().requiredParams())) {
                return m.tool();
            }
        }
        return ranked.get(0).tool();
    }

    private Object scoreOf(ScfyToolDescriptor tool, List<ToolMatcher.Match> ranked) {
        for (ToolMatcher.Match m : ranked) {
            if (m.tool().toolCode().equals(tool.toolCode())) {
                return m.score();
            }
        }
        return null;
    }

    private List<String> reasonsOf(ScfyToolDescriptor tool, List<ToolMatcher.Match> ranked) {
        for (ToolMatcher.Match m : ranked) {
            if (m.tool().toolCode().equals(tool.toolCode())) {
                return m.reasons();
            }
        }
        return List.of();
    }

    /** 调用工具。异常在这里被收成结构化失败，不往上抛 —— 抛出去模型只会看到「调用失败」。 */
    private Map<String, Object> invoke(ScfyToolDescriptor tool, Map<String, Object> args,
                                       Map<String, Object> out) {
        try {
            Object r = registry.invoke(tool.toolCode(), args, ToolCallContext.system());
            if (r instanceof Map<?, ?> m) {
                @SuppressWarnings("unchecked")
                Map<String, Object> mm = (Map<String, Object>) m;
                return mm;
            }
            Map<String, Object> wrap = new LinkedHashMap<>();
            wrap.put("ok", true);
            wrap.put("data", r);
            return wrap;
        } catch (Exception e) {
            log.warn("scfy agent 调用失败 tool={} args={}", tool.toolCode(), args, e);
            out.put("ok", false);
            out.put("errors", List.of("调用工具 " + tool.toolCode() + " 失败：" + e.getMessage()));
            return null;
        }
    }

    private static void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String key) {
        if (from.containsKey(key)) {
            to.put(key, from.get(key));
        }
    }

    /** 匹配不到时的提示：把「能查什么」和「该怎么说」一起给出，而不是干巴巴一句没匹配到。 */
    private String noMatchHint(List<ToolMatcher.Match> ranked) {
        StringBuilder sb = new StringBuilder();
        sb.append("没有匹配到合适的查询接口（最高相关度 ")
                .append(ranked.isEmpty() ? "0" : String.valueOf(ranked.get(0).score()))
                .append("，低于阈值 ").append(matcher.minScore()).append("）。");
        sb.append("当前可查询的范围：");
        List<String> groups = new ArrayList<>();
        for (ScfyToolDescriptor d : catalog().registered()) {
            if (!groups.contains(d.group())) {
                groups.add(d.group());
            }
        }
        sb.append(String.join(" / ", groups));
        sb.append("。可换个说法，例如「成都有哪些非遗工坊」「甘孜州有多少非遗项目」。");
        return sb.toString();
    }

    // ==================== 清单 ====================

    /**
     * 注册清单 —— 每个接口的名称、用途、参数、返回结构。
     * 这就是「注册到 agent」这件事的可读载体：模型可以先看清单，再决定调用。
     *
     * @param group   只看某个分组（可空）
     * @param keyword 按名称/用途过滤（可空）
     */
    public Map<String, Object> catalogList(String group, String keyword) {
        List<Map<String, Object>> items = new ArrayList<>();
        int skipped = 0;
        for (ScfyToolDescriptor d : catalog().all()) {
            if (group != null && !group.isBlank() && !group.equals(d.group())) {
                continue;
            }
            if (keyword != null && !keyword.isBlank()
                    && !d.searchText().toLowerCase().contains(keyword.toLowerCase())) {
                continue;
            }
            items.add(d.toMap());
            if (!d.returnsData()) {
                skipped++;
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", catalog().size());
        out.put("autoMatchable", catalog().registered().size());
        out.put("excludedFromAutoMatch", catalog().excluded().size());
        out.put("matched", items.size());
        out.put("note", "返回结构来自生产实测采集（observed=OK_DATA 才是真实观测到的形状）。"
                + "排除自动匹配的接口调用成功但不返回数据，用它们只会得到「查到了但没结果」。");
        out.put("items", items);
        if (skipped > 0) {
            out.put("excludedInThisView", skipped);
        }
        return out;
    }

    /** 某个接口的完整注册信息（名称/用途/参数/返回结构）。 */
    public Map<String, Object> describe(String toolCode) {
        ScfyToolDescriptor d = catalog().byToolCode(toolCode);
        Map<String, Object> out = new LinkedHashMap<>();
        if (d == null) {
            out.put("ok", false);
            out.put("errors", List.of("没有这个工具：" + toolCode));
            return out;
        }
        out.put("ok", true);
        out.putAll(d.toMap());
        List<Map<String, Object>> ps = new ArrayList<>();
        for (ScfyParam p : d.params()) {
            Map<String, Object> pm = new LinkedHashMap<>();
            pm.put("name", p.name());
            pm.put("required", p.required());
            pm.put("type", p.type());
            pm.put("description", p.description());
            if (p.hasEnums()) {
                pm.put("enums", p.enums());
            }
            if (p.docNote() != null && !p.docNote().isBlank()) {
                pm.put("docNote", p.docNote());
            }
            ps.add(pm);
        }
        out.put("paramsDetail", ps);
        return out;
    }
}
