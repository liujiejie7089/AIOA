package cn.aioa.integration.scfy.agent;

import cn.aioa.integration.scfy.contract.ScfyParam;
import cn.aioa.integration.scfy.core.ScfyEnums;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 从自然语言提问里抽取接口参数。
 *
 * <p><b>它只做「提问里明说了的」事，不做推断</b>：抽不到就留空，
 * 让校验器去生成追问话术。理由是这个系统对参数错误是<b>静默的</b>（返回空结果、code=0），
 * 一旦这里「猜一个默认值」，用户会拿到一份看不出错的假结论。
 * 例：把「甘孜藏族自治州」当市州名传下去，实测返回 0 条且不报错 ——
 * 用户会以为甘孜州没有非遗数据。</p>
 *
 * <p>抽取规则对应契约里实际出现的参数名，不按「参数名像什么」猜：
 * 同一个名字 {@code area} 在不同接口上含义不同（市州简称 / 12 位行政区划编码），
 * 因此抽取依据是<b>参数名 + 契约声明的类型</b>，而不是参数名本身。</p>
 */
public class ScfyParamExtractor {

    /** 官方长名 → 实测可用的简称。文档给的是长名，实测只有简称能查出数据。 */
    private static final Map<String, String> FULL_CITY_NAMES = new LinkedHashMap<>();

    static {
        FULL_CITY_NAMES.put("甘孜藏族自治州", "甘孜州");
        FULL_CITY_NAMES.put("阿坝藏族羌族自治州", "阿坝州");
        FULL_CITY_NAMES.put("凉山彝族自治州", "凉山州");
        FULL_CITY_NAMES.put("成都市", "成都市");
    }

    /** 等级说法 → 契约枚举值（{@link ScfyEnums#LEVELS}）。 */
    private static final Map<String, String> LEVEL_WORDS = new LinkedHashMap<>();

    static {
        LEVEL_WORDS.put("联合国教科文组织", "un");
        LEVEL_WORDS.put("联合国级", "un");
        LEVEL_WORDS.put("联合国", "un");
        LEVEL_WORDS.put("世界级", "un");
        LEVEL_WORDS.put("国家级", "country");
        LEVEL_WORDS.put("省级", "province");
        LEVEL_WORDS.put("市级", "city");
        LEVEL_WORDS.put("县级", "county");
    }

    private static final Pattern P_12DIGIT = Pattern.compile("\\d{12}");
    private static final Pattern P_UUID = Pattern.compile(
            "\\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?:_[a-z]+)?");
    private static final Pattern P_HEX32 = Pattern.compile("\\b[0-9a-fA-F]{32}\\b");
    private static final Pattern P_PROJECT_ID = Pattern.compile("\\b\\d{1,4}-[A-Z]{2,3}-\\d{1,6}\\b");
    /** 「工坊 id=140」「编号：140」这类显式写法才认纯数字 id，避免把年份/条数当 id。 */
    private static final Pattern P_LABELLED_NUM_ID = Pattern.compile(
            "(?:id|ID|编号)\\s*[:：=＝]?\\s*(\\d{1,8})");
    private static final Pattern P_PAGE_SIZE = Pattern.compile("(?:前|最多|返回|要|取)?\\s*(\\d{1,3})\\s*[条个]");
    private static final Pattern P_TOP_NUM =
            Pattern.compile("(?:排名前|最热门|热门|最新|前|top|TOP)\\s*的?\\s*(\\d{1,3})");
    private static final Pattern P_PAGE_NUM = Pattern.compile("第\\s*(\\d{1,3})\\s*页");
    /** 区县名：2~3 个汉字 + 区/县（市州名以 市/州 结尾；要求前面不是汉字，避免从长词中间切开）。 */
    private static final Pattern P_DISTRICT =
            Pattern.compile("(?<![\\u4e00-\\u9fa5])([\\u4e00-\\u9fa5]{2,3}[区县])");
    /** 常见连接词：出现在候选区县名开头说明这个候选是从一句话里切歪的（如「和锦江区」）。 */
    private static final String CONNECTIVES = "和与及在的以从到去并或就也都很最";

    /**
     * 抽取结果。
     *
     * @param args     可直接交给工具调用的参数
     * @param evidence 每个参数是「从提问里的哪个片段」抽出来的 —— 用于向用户解释参数来路，
     *                 也用于排查「为什么这次没抽到」
     */
    public record Extraction(Map<String, Object> args, Map<String, String> evidence) {

        public static Extraction empty() {
            return new Extraction(Map.of(), Map.of());
        }
    }

    /** 按参数名 + 契约类型抽参。 */
    public Extraction extract(String question, ScfyToolDescriptor tool) {
        if (question == null || question.isBlank() || tool == null) {
            return Extraction.empty();
        }
        Map<String, Object> args = new LinkedHashMap<>();
        Map<String, String> evidence = new LinkedHashMap<>();

        for (ScfyParam p : tool.params()) {
            Object v = extractOne(question, p);
            if (v != null && !String.valueOf(v).isBlank()) {
                args.put(p.name(), v);
                evidence.put(p.name(), String.valueOf(v));
            }
        }
        return new Extraction(args, evidence);
    }

    /** 单个参数的抽取规则。返回 null 表示「提问里没明说」。 */
    private Object extractOne(String q, ScfyParam p) {
        String name = p.name();
        String type = p.type() == null ? "string" : p.type();

        // 行政区划编码类参数：只认 12 位编码。
        // 传名称或 6 位编码实测返回全零且不报错，所以这里宁可抽不到（转追问）也不凑合。
        if ("areaCode".equals(type) || "areaId".equals(name) || "cityCode".equals(name)) {
            return firstMatch(P_12DIGIT, q);
        }

        switch (name) {
            case "level":
                return levelWord(q);
            case "pageSize":
                return clamp(intMatch(P_PAGE_SIZE, q), 1, ScfyEnums.MAX_PAGE_SIZE);
            case "pageNum":
                return clamp(intMatch(P_PAGE_NUM, q), 1, 100);
            case "topNum":
                return clamp(intMatch(P_TOP_NUM, q), 1, 50);
            case "areaName":
                return district(q);
            case "area", "cityName":
                return city(q);
            case "name":
                // 该参数只用于「全省汇总」这类固定口径；提问里通常不会说，不猜
                return null;
            case "id":
            case "dataId":
            case "projectBaseId":
            case "inheritorId":
            case "travelId":
            case "ecologicalAreaId":
            case "shopId":
                return idLike(q);
            default:
                return null;
        }
    }

    // ==================== 各类抽取 ====================

    /**
     * 市州：先认官方长名（文档写法），再认简称，最后认去掉「市/州」的词干。
     * <p>顺序不能颠倒 —— 「甘孜藏族自治州」里含「甘孜州」吗？不含（中间有字），
     * 但「阿坝藏族羌族自治州」里也不含「阿坝州」。所以长名必须在简称之前判定，
     * 否则长名会先命中「阿坝」这个词干并返回简称，看起来对、其实漏了归一化这一步。</p>
     */
    static String city(String q) {
        for (Map.Entry<String, String> e : FULL_CITY_NAMES.entrySet()) {
            if (q.contains(e.getKey())) {
                return e.getValue();
            }
        }
        // 简称：长名优先（阿坝州 比 阿坝 更具体）
        List<String> cities = new ArrayList<>(ScfyEnums.CITIES);
        cities.sort((a, b) -> Integer.compare(b.length(), a.length()));
        for (String c : cities) {
            if (q.contains(c)) {
                return c;
            }
        }
        // 词干（成都市 → 成都）：用户常省略行政级别后缀
        for (String c : cities) {
            String stem = stem(c);
            if (stem.length() >= 2 && q.contains(stem)) {
                return c;
            }
        }
        return null;
    }

    private static String stem(String city) {
        if (city.endsWith("自治州")) {
            return city.substring(0, city.length() - 3);
        }
        if (city.endsWith("市") || city.endsWith("州")) {
            return city.substring(0, city.length() - 1);
        }
        return city;
    }

    /** 等级：只认明确说法，不认孤立的「省」「市」「县」（那会和地名撞）。 */
    static String levelWord(String q) {
        for (Map.Entry<String, String> e : LEVEL_WORDS.entrySet()) {
            if (q.contains(e.getKey())) {
                return e.getValue();
            }
        }
        // 也接受直接写枚举值（程序化调用/英文提问）
        String lower = q.toLowerCase(Locale.ROOT);
        for (String lv : ScfyEnums.LEVELS) {
            if (Pattern.compile("\\b" + lv + "\\b").matcher(lower).find()) {
                return lv;
            }
        }
        return null;
    }

    /**
     * 区县名。
     *
     * <p><b>必须先把市州名从提问里摘掉再找区县</b>：{@code 成都市锦江区} 直接套
     * 「2~4 个汉字 + 区/县」会从中间切开，匹配出 {@code 都市锦江区} 这种既不是市州、
     * 也不是区县的名字，然后被当成区县传给接口 —— 而接口对错值不报错，只返回空结果。
     * 摘掉 {@code 成都市} 之后剩下 {@code 锦江区}，才是干净答案。</p>
     */
    static String district(String q) {
        if (q == null) {
            return null;
        }
        Matcher m = P_DISTRICT.matcher(stripCityNames(q));
        while (m.find()) {
            String cand = m.group(1);
            if (cand.length() < 2 || CONNECTIVES.indexOf(cand.charAt(0)) >= 0) {
                continue;
            }
            if (ScfyEnums.CITIES.contains(cand)) {
                continue;
            }
            return cand;
        }
        return null;
    }

    /** 把提问里的市州名（全称 / 简称 / 词干）替换成空格，长名优先，避免「成都市」被「成都」抢先匹配。 */
    static String stripCityNames(String q) {
        String s = q;
        List<String> keys = new ArrayList<>(FULL_CITY_NAMES.keySet());
        List<String> cities = new ArrayList<>(ScfyEnums.CITIES);
        for (String c : cities) {
            String stem = stem(c);
            if (stem.length() >= 2) {
                keys.add(stem);
            }
        }
        keys.addAll(cities);
        keys.sort((a, b) -> Integer.compare(b.length(), a.length()));
        for (String k : keys) {
            if (k.length() >= 2) {
                s = s.replace(k, " ");
            }
        }
        return s;
    }

    /** id 类参数：UUID / 32 位十六进制 / 项目编码 / 显式标注的数字 id。 */
    static String idLike(String q) {
        String v = firstMatch(P_UUID, q);
        if (v == null) {
            v = firstMatch(P_PROJECT_ID, q);
        }
        if (v == null) {
            v = firstMatch(P_HEX32, q);
        }
        if (v == null) {
            v = firstMatch(P_LABELLED_NUM_ID, q);
        }
        return v;
    }

    // ==================== 小工具 ====================

    private static String firstMatch(Pattern p, String q) {
        Matcher m = p.matcher(q);
        if (!m.find()) {
            return null;
        }
        return m.groupCount() >= 1 ? m.group(1) : m.group(0);
    }

    private static Integer intMatch(Pattern p, String q) {
        String s = firstMatch(p, q);
        if (s == null) {
            return null;
        }
        try {
            return Integer.valueOf(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Integer clamp(Integer v, int lo, int hi) {
        if (v == null) {
            return null;
        }
        return Math.max(lo, Math.min(hi, v));
    }
}
