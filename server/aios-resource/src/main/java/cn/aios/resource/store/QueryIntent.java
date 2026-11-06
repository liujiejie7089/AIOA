package cn.aios.resource.store;

import java.util.regex.Pattern;

/**
 * 查询意图判定（docs/74 P0-2）：只区分「聚合类」与其它，不猜领域。
 *
 * <p>为什么要它：统计摘要块与普通数据行块<b>同分</b>（实测 0.01639 vs 0.01613），
 * 靠分数让它排第一是碰运气 —— 换个插入顺序就掉下去。因此聚合类问题必须
 * <b>按意图显式置顶</b>，而不是指望排序。</p>
 *
 * <p>判定刻意保守：宁可漏判（少注入一块摘要，无害），也不要把普通问句都当聚合法 ——
 * 误判的代价是 top5 里被摘要挤掉一条明细。</p>
 */
public final class QueryIntent {

    /** 聚合类信号词：计数 / 汇总 / 分组 / 排序。 */
    private static final Pattern AGGREGATE = Pattern.compile(
            "多少|几[个项条人家种批]|数量|总数|合计|共计|一共|总共|统计|汇总|"
                    + "排名|排序|占比|比例|分别|平均|最多|最少|最大|最小|前几|列出全部|一共有");

    private QueryIntent() {
    }

    /** 是否是聚合类问题（「共有多少条」「按类别分别多少个」）。 */
    public static boolean aggregate(String query) {
        return query != null && !query.isBlank() && AGGREGATE.matcher(query).find();
    }
}
