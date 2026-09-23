package cn.aioa.integration.scfy.agent;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * 默认匹配器：确定性词法匹配（中文二元组 + IDF + 字段/名称加权）。
 *
 * <p><b>为什么默认不用向量或大模型</b>：这一层要回答的是「这句话该用哪个查询」，
 * 而候选集只有几十个、每个都有我们自己写的用途描述与实测字段名 —— 信息密度很高。
 * 词法匹配在这种规模上已经够用，而它有三个向量方案给不了的性质：
 * <b>零外部依赖</b>（不引入嵌入服务，不因外部系统不可用而失效）、
 * <b>结果确定可复现</b>（同一句话永远同一个接口，测试可以钉死）、
 * <b>可解释</b>（能说出命中哪些词，用户看到「因为命中 工坊、销售额」会信任这个结论）。
 * 等词法真的不够用了，再按 {@link ToolMatcher} 换实现即可。</p>
 *
 * <p><b>打分口径</b>（全部落在 0~1）：</p>
 * <ol>
 *   <li>把提问切成词：中文取二元组（bigram，不需要分词器），英文数字取整串；</li>
 *   <li>用 IDF 给词加权 —— 在少数接口里出现的词（如「工坊」「销售额」）比遍地都是的词更有信息量；</li>
 *   <li>每个接口的检索文本里，<b>名称/字段名里的词权重大于描述里的词</b>（1.4 / 1.2 vs 1.0）；</li>
 *   <li>得分为「提问的信息量被该接口覆盖的比例」；</li>
 *   <li>命中业务别名（如「店铺」→ 工坊）额外加权。</li>
 * </ol>
 *
 * <p>排序在分数相同时按「必填参数少 → 工具编码字典序」打破平局，
 * 保证<b>同一句话的匹配结果永远一致</b>（否则测试与用户都会看到随机结果）。</p>
 */
public class LexicalToolMatcher implements ToolMatcher {

    /**
     * 低于此分数视为没有匹配。
     * <p>取值依据（在 {@code ScfyToolMatcherTest} 里用真实问句钉死）：
     * 问句的信息量若有一半以上落在该接口的描述/字段上，才算「说得就是它」。
     * 定得再低，「四川有哪些非遗项目」这类问句会把工坊、旅游接口一起拉进来。</p>
     */
    private static final double MIN_SCORE = 0.45;

    /** 名称里的词权重。 */
    private static final double W_NAME = 1.4;
    /** 返回字段名里的词权重 —— 用户常按结果字段提问，命中字段说明问的就是它。 */
    private static final double W_FIELD = 1.2;
    /** 描述/参数说明里的词权重。 */
    private static final double W_DESC = 1.0;
    /** 业务别名命中分组的加权。 */
    private static final double ALIAS_BOOST = 0.22;
    /** 提问意图与接口类型一致时的加权。 */
    private static final double INTENT_BOOST = 0.16;
    /** 提问意图与接口类型相左时的减权 —— 比不加权更强，否则「有哪些」会落到计数接口上。 */
    private static final double INTENT_MISMATCH_PENALTY = 0.15;
    /** 提问点明了市州、而接口根本没有能接受市州名的参数时的减权。 */
    private static final double NO_CITY_SCOPE_PENALTY = 0.25;

    /** 「要一张清单」的说法。 */
    private static final List<String> LIST_INTENT_WORDS = List.of(
            "有哪些", "哪些", "列出", "列表", "名单", "清单", "有什么", "都有什么", "分别是");
    /** 「要一个数」的说法。 */
    private static final List<String> COUNT_INTENT_WORDS = List.of(
            "多少", "几个", "数量", "总数", "共计", "一共", "统计", "多少个");
    /** 接口侧「这是清单类接口」的标志。 */
    private static final List<String> LIST_TOOL_MARKERS = List.of("列表", "名单", "清单");
    /** 接口侧「这是计数类接口」的标志。 */
    private static final List<String> COUNT_TOOL_MARKERS = List.of("数量", "统计", "汇总", "计数");
    /** 能接受「市州/区县」的参数字名 —— 决定该接口能否回答「某某地」的问题。 */
    private static final List<String> CITY_SCOPE_PARAMS = List.of("area", "cityName", "areaId", "cityCode");

    /**
     * 业务别名 → 应命中的分组。
     * <p>用户不会说「工坊」以外的官方词（会说店铺、作坊、门店），
     * 这些说法在任何接口描述里都不出现，纯词法匹配必然漏 —— 别名表补的就是这类缺口。</p>
     */
    private static final Map<String, String> GROUP_ALIASES = new LinkedHashMap<>();

    static {
        alias("工坊", "工坊", "店铺", "门店", "作坊", "商家", "经营者", "老字号");
        alias("传承人", "传承人", "传承者", "大师", "非遗大师", "代表性传承人", "手艺人", "匠人");
        alias("项目", "项目", "名录", "非遗名录", "代表性项目", "非遗项目");
        alias("保护区", "保护区", "生态区", "文化生态保护区", "生态保护区", "集聚区");
        alias("旅游", "旅游", "线路", "旅游线路", "景区", "民宿", "自驾", "非遗之旅", "体验基地", "重点县");
    }

    private static void alias(String group, String... words) {
        for (String w : words) {
            GROUP_ALIASES.put(w, group);
        }
    }

    /** 纯功能词，不携带业务信息 —— 留着它们只会让所有接口的分数一起抬高。 */
    private static final Set<String> STOPWORDS = Set.of(
            "什么", "哪些", "多少", "几个", "怎么", "如何", "帮我", "一下", "我想", "请问",
            "有没", "没有", "是不", "不是", "这个", "那个", "以及", "还有", "查询", "查一",
            "统计", "情况", "相关", "关于", "信息", "数据", "内容", "可以", "能否", "告诉");

    @Override
    public String name() {
        return "lexical-bigram-idf";
    }

    @Override
    public double minScore() {
        return MIN_SCORE;
    }

    @Override
    public List<Match> rank(String question, List<ScfyToolDescriptor> candidates, int topN) {
        if (question == null || question.isBlank() || candidates == null || candidates.isEmpty()) {
            return List.of();
        }
        Set<String> qTerms = tokenize(question);
        if (qTerms.isEmpty()) {
            return List.of();
        }

        // 每个接口的加权词表
        Map<String, Map<String, Double>> toolTerms = new LinkedHashMap<>();
        for (ScfyToolDescriptor d : candidates) {
            toolTerms.put(d.toolCode(), termsOf(d));
        }

        // 文档频率 → IDF（用整个候选集算，保证与候选集一致）
        Map<String, Integer> df = new LinkedHashMap<>();
        for (Map<String, Double> terms : toolTerms.values()) {
            for (String t : terms.keySet()) {
                df.merge(t, 1, Integer::sum);
            }
        }
        int n = candidates.size();

        double qMass = 0;
        for (String t : qTerms) {
            qMass += idf(t, df, n);
        }
        if (qMass <= 0) {
            return List.of();
        }

        // 提问里点明的地名（用于判断接口能不能接受它）
        String askedCity = ScfyParamExtractor.city(question);

        List<Scored> scored = new ArrayList<>();
        for (ScfyToolDescriptor d : candidates) {
            Map<String, Double> terms = toolTerms.get(d.toolCode());
            double hit = 0;
            List<String> reasons = new ArrayList<>();
            for (String t : qTerms) {
                Double w = terms.get(t);
                if (w != null) {
                    hit += idf(t, df, n) * w;
                    if (reasons.size() < 6) {
                        reasons.add(t);
                    }
                }
            }
            double rawScore = hit / qMass;

            String aliased = aliasGroup(question);
            if (aliased != null && aliased.equals(d.group())) {
                rawScore += ALIAS_BOOST;
                reasons.add("业务别名→" + d.group());
            }

            // 意图：问「有哪些」要清单，问「有多少」要数量。这两类问题在本系统里
            // 落在不同接口上（列表 vs 计数），仅凭用词相似度分不开 —— 两边描述里
            // 都会出现「非遗项目」「市州」这些词。
            Intent intent = intentOf(question);
            if (intent == Intent.LIST) {
                if (isListTool(d)) {
                    rawScore += INTENT_BOOST;
                    reasons.add("意图=要清单");
                } else if (isCountTool(d)) {
                    rawScore -= INTENT_MISMATCH_PENALTY;
                    reasons.add("意图相左(问清单/是计数)");
                }
            } else if (intent == Intent.COUNT) {
                if (isCountTool(d)) {
                    rawScore += INTENT_BOOST;
                    reasons.add("意图=要数量");
                } else if (isListTool(d)) {
                    rawScore -= INTENT_MISMATCH_PENALTY;
                    reasons.add("意图相左(问数量/是清单)");
                }
            }

            // 地名可施加性：提问点明了市州，而该接口没有任何能收市州名的参数 ——
            // 它答不了「成都有多少」这种带地名的问法（例如只按等级统计的计数接口），
            // 即便用词很像也不该胜出。
            if (askedCity != null && !acceptsCity(d)) {
                rawScore -= NO_CITY_SCOPE_PENALTY;
                reasons.add("不接受地名参数(" + askedCity + ")");
            }

            // 只把负分归零，不做上截顶 —— 截顶会抹掉候选之间的差距
            rawScore = Math.max(0, rawScore);

            // 名称整体出现的强信号：用户往往直接说工具名（或它的中文名）
            if (contains(question, d.name())) {
                rawScore += 0.3;
                reasons.add("命中名称");
            }

            if (rawScore <= 0) {
                continue;
            }
            // 保留未截顶的分数用于排序：一旦先截到 1.0，多条候选就会并成同一个分数，
            // 排序只能靠编码字典序决胜负 —— 那是随机结果，不是匹配结果
            scored.add(new Scored(d, rawScore, dedupe(reasons)));
        }

        // 确定性排序：真实分高优先，其次必填参数少的（更可能一把调通），最后按编码
        scored.sort(Comparator.comparingDouble(Scored::raw).reversed()
                .thenComparing(s -> s.tool().requiredParams().size())
                .thenComparing(s -> s.tool().toolCode()));

        List<Match> out = new ArrayList<>();
        for (Scored s : scored) {
            out.add(new Match(s.tool(), round(Math.min(1.0, s.raw())), s.reasons()));
            if (out.size() >= topN) {
                break;
            }
        }
        return List.copyOf(out);
    }

    /** 排序用的中间结构：raw 是未截顶的分数。 */
    private record Scored(ScfyToolDescriptor tool, double raw, List<String> reasons) {
    }

    // ==================== 词表与打分 ====================

    /** 提问的意图类别 —— 决定它要一张清单还是要一个数。 */
    enum Intent {
        LIST, COUNT, NONE
    }

    static Intent intentOf(String question) {
        if (question == null) {
            return Intent.NONE;
        }
        boolean list = LIST_INTENT_WORDS.stream().anyMatch(question::contains);
        boolean count = COUNT_INTENT_WORDS.stream().anyMatch(question::contains);
        if (list && !count) {
            return Intent.LIST;
        }
        if (count && !list) {
            return Intent.COUNT;
        }
        return Intent.NONE;
    }

    /**
     * 该接口是清单类还是计数类 —— <b>只看名称，不看描述</b>。
     *
     * <p>描述里会<b>交叉引用别的工具</b>（列表接口的说明写着「按等级查数量请改用
     * scfy_project_count_by_area」），拿描述判类型会把列表接口误判成计数接口，
     * 于是「有多少」的问题被推向列表接口。名称是各自唯一的、不引用他人的字段，判类型只能用它。</p>
     */
    private static boolean isListTool(ScfyToolDescriptor d) {
        String name = d.name() == null ? "" : d.name();
        return LIST_TOOL_MARKERS.stream().anyMatch(name::contains);
    }

    private static boolean isCountTool(ScfyToolDescriptor d) {
        String name = d.name() == null ? "" : d.name();
        return COUNT_TOOL_MARKERS.stream().anyMatch(name::contains);
    }

    /** 该接口有没有能接受市州/区县的参数。 */
    private static boolean acceptsCity(ScfyToolDescriptor d) {
        for (String p : CITY_SCOPE_PARAMS) {
            for (cn.aioa.integration.scfy.contract.ScfyParam declared : d.params()) {
                if (p.equals(declared.name())) {
                    return true;
                }
            }
        }
        return false;
    }

    /** 一个接口的加权词表：名称词最重，字段名次之，描述与参数说明再次。 */
    private static Map<String, Double> termsOf(ScfyToolDescriptor d) {
        Map<String, Double> m = new LinkedHashMap<>();
        addAll(m, tokenize(d.name()), W_NAME);
        addAll(m, tokenize(d.group()), W_DESC);
        addAll(m, tokenize(d.purpose()), W_DESC);
        // 参数名只在完全一致时才有意义，故用整词而不切二元组
        for (String p : d.requiredParams()) {
            m.merge(p.toLowerCase(Locale.ROOT), W_DESC, Math::max);
        }
        addAll(m, tokenize(fieldText(d)), W_FIELD);
        return m;
    }

    /** 返回结构里的字段名（含嵌套数组元素字段），作为检索词。 */
    private static String fieldText(ScfyToolDescriptor d) {
        return d.returnsText();
    }

    private static void addAll(Map<String, Double> target, Set<String> terms, double weight) {
        for (String t : terms) {
            target.merge(t, weight, Math::max);
        }
    }

    private static double idf(String term, Map<String, Integer> df, int n) {
        int d = df.getOrDefault(term, 0);
        return Math.log(1.0 + (double) n / (1.0 + d));
    }

    /**
     * 切词：中文二元组 + 英文数字整串。
     * <p>不引分词器 —— 二元组在「短问句 vs 短描述」这个场景里召回已经足够，
     * 而且没有词典就意味着不会因为缺少某个领域词而整句切不出来。</p>
     */
    static Set<String> tokenize(String text) {
        Set<String> terms = new LinkedHashSet<>();
        if (text == null) {
            return terms;
        }
        StringBuilder cjk = new StringBuilder();
        StringBuilder ascii = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (isCjk(c)) {
                flushAscii(ascii, terms);
                cjk.append(c);
            } else if (Character.isLetterOrDigit(c)) {
                flushCjk(cjk, terms);
                ascii.append(Character.toLowerCase(c));
            } else {
                flushAscii(ascii, terms);
                flushCjk(cjk, terms);
            }
        }
        flushAscii(ascii, terms);
        flushCjk(cjk, terms);
        terms.removeAll(STOPWORDS);
        return terms;
    }

    private static void flushAscii(StringBuilder sb, Set<String> out) {
        if (sb.length() >= 2) {
            out.add(sb.toString());
        }
        sb.setLength(0);
    }

    private static void flushCjk(StringBuilder sb, Set<String> out) {
        String s = sb.toString();
        if (s.length() == 1) {
            out.add(s);
        }
        for (int i = 0; i + 1 < s.length(); i++) {
            out.add(s.substring(i, i + 2));
        }
        sb.setLength(0);
    }

    private static boolean isCjk(char c) {
        return c >= 0x4E00 && c <= 0x9FFF;
    }

    private static String aliasGroup(String question) {
        for (Map.Entry<String, String> e : GROUP_ALIASES.entrySet()) {
            if (question.contains(e.getKey())) {
                return e.getValue();
            }
        }
        return null;
    }

    private static boolean contains(String haystack, String needle) {
        return needle != null && !needle.isBlank() && haystack.contains(needle);
    }

    private static List<String> dedupe(List<String> in) {
        return List.copyOf(new LinkedHashSet<>(in));
    }

    private static double round(double v) {
        return Math.round(v * 1000.0) / 1000.0;
    }

    /** 别名表只读视图，供测试与文档复用。 */
    public static Map<String, String> groupAliases() {
        return Map.copyOf(GROUP_ALIASES);
    }
}
