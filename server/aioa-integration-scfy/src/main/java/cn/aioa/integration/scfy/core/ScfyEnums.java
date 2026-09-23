package cn.aioa.integration.scfy.core;

import java.util.List;

/**
 * scfy 的枚举事实源 —— 参数校验与工具 Schema 都从这里取，不允许别处再写一份。
 *
 * <p><b>本类的取值全部来自 2026-09-23 生产实测，不是从接口文档抄的</b>。
 * 文档在这三处与实测冲突，冲突已固化为常量：
 * <ol>
 *   <li><b>市州必须用简称</b>：文档第十一节写「使用中文全称，如 {@code 甘孜藏族自治州}」，
 *       实测该值返回 <b>0 条</b>（code=0，静默空结果，不报错）；正确值是 {@code 甘孜州}（291 条）。
 *       这是最危险的一处 —— 模型照文档传全称会拿到空数组，用户会以为「四川没有这个数据」。</li>
 *   <li><b>level 只有 {@code country} 真正生效</b>：{@code un}/{@code province}/{@code city}/{@code county}
 *       实测返回的 total 与「未过滤」完全相同（1241），即后端把未识别的值静默降级为默认查询。
 *       传 {@code un} 不会报错、也不会筛出联合国级 —— 它只是被忽略了。</li>
 *   <li><b>level 在不同接口上的语义不一致</b>：{@code /show/project/getProjectListByArea}
 *       传任何 level（含不传）都是 1411 条，该参数被完全忽略；而
 *       {@code /show/project/getProjectTypeData} 不传 level 直接 500（必填）。</li>
 * </ol>
 *
 * <p><b>为什么 {@link #LEVELS} 仍保留 {@code un}</b>：数据里确实存在「联合国级」这一档
 * （见 {@code getProjectCountByArea} 返回的 {@code level_name=联合国教科文组织}），
 * 它是合法<em>数据档位</em>，只是当前不是有效的<em>查询参数值</em>。
 * 枚举保留 {@code un} 但配套 {@link #LEVEL_FILTER_WARNING}，让校验器与工具描述
 * 把「传了等于没传」这件事说出来 —— 这比直接删掉该值更能防止误用。</p>
 */
public final class ScfyEnums {

    private ScfyEnums() {
    }

    /** 等级枚举（含联合国级）。顺序即业务层级，供工具 description 展示。 */
    public static final List<String> LEVELS = List.of("un", "country", "province", "city", "county");

    /** 等级值的中文名，用于把枚举翻译成人话（追问话术与管理端展示）。 */
    public static String levelLabel(String code) {
        if (code == null) {
            return "";
        }
        return switch (code) {
            case "un" -> "联合国级";
            case "country" -> "国家级";
            case "province" -> "省级";
            case "city" -> "市级";
            case "county" -> "县级";
            default -> code;
        };
    }

    /**
     * 等级过滤的实测警示 —— 必须出现在每一个含 level 参数的工具描述里。
     * <p>不写这句，模型会以为「传 level=un 就筛出联合国级」，而实际拿到的是全省数据，
     * 且用户无法从结果里察觉。</p>
     */
    public static final String LEVEL_FILTER_WARNING =
            "实测警示：level 参数目前只有 country（国家级）真正生效；"
                    + "un/province/city/county 会被后端静默忽略并返回未过滤结果（不报错）。"
                    + "若用户想精确筛选联合国级，请改用 project_count_by_area 查看各档位数量，不要依赖 level。";

    /** 市州名称 —— 21 个，实测取自 getAreaInheritorData 的 short_name（去重）。 */
    public static final List<String> CITIES = List.of(
            "成都市", "自贡市", "攀枝花市", "泸州市", "德阳市", "绵阳市", "广元市", "遂宁市",
            "内江市", "乐山市", "南充市", "眉山市", "宜宾市", "广安市", "达州市", "雅安市",
            "巴中市", "资阳市", "阿坝州", "甘孜州", "凉山州");

    /**
     * 市州名称的实测警示。
     * <p>文档给的示例是「甘孜藏族自治州」，实测必须写简称「甘孜州」，否则返回空集。</p>
     */
    public static final String CITY_NAME_WARNING =
            "市州必须用简称（如 甘孜州 / 阿坝州 / 凉山州），不要用全称（甘孜藏族自治州 会返回 0 条且不报错）。"
                    + "不传该参数表示全省数据。";

    /** 非遗十大门类 —— 实测取自 getProjectTypeData 的 data[].name。 */
    public static final List<String> PROJECT_CATEGORIES = List.of(
            "民间文学", "传统音乐", "传统舞蹈", "传统戏剧", "曲艺",
            "传统体育、游艺与杂技", "传统美术", "传统技艺", "传统医药", "民俗");

    /** 分页默认值 —— 文档第十一节声明，实测一致。 */
    public static final int DEFAULT_PAGE_NUM = 1;
    public static final int DEFAULT_PAGE_SIZE = 10;
    public static final int MAX_PAGE_SIZE = 100;

    /** 判断是否为实测确认合法的市州。 */
    public static boolean isKnownCity(String area) {
        return area != null && CITIES.contains(area.trim());
    }
}
