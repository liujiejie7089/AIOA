package cn.aios.resource.store;

import cn.aios.resource.entity.KbChunk;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 关键词打分：char 2-gram 上的 BM25（2026-11-06 由「覆盖率 × 命中数」升级，docs/74 根因 4）。
 *
 * <p><b>为什么换</b>：原口径是 {@code hit / |qgrams| × (1 + ln(1+hit))}，只有"覆盖率"一个维度，
 * <b>没有 IDF、也没有文档长度归一</b>。后果是<b>同构的行分数完全相同</b>——实测一张 500 行的
 * 名录表，501 个切片全部落在 0.2209 附近，RRF 融合后只能按 {@code chunk_index} 排序，
 * 于是 top5 永远是"表格前 5 行"，与问题无关。这不是"分低"，是<b>没有区分度</b>。</p>
 *
 * <p><b>换成什么</b>：标准 BM25（k1=1.2, b=0.75），三项都补齐：</p>
 * <ul>
 *   <li><b>IDF</b>：{@code ln(1 + (N - df + 0.5) / (df + 0.5))} —— "项目/序号"这种到处都是的
 *       gram 权重自动压低，"非遗/川剧"这种稀有 gram 权重抬高；</li>
 *   <li><b>TF 饱和</b>：{@code f(k1+1)/(f + k1·…)} —— 一个 gram 出现 10 次不等于"相关 10 倍"；</li>
 *   <li><b>长度归一</b>：{@code 1 - b + b·dl/avgdl} —— 长切片不再天然占优。</li>
 * </ul>
 *
 * <p>候选集内的 df/avgdl 现算（与 {@link MysqlKnowledgeStore} 的候选口径一致），
 * 因此两种 store 的兜底路径仍然同源；{@link RrfFusion} 只吃排名，不受分数量纲影响。</p>
 */
public final class KeywordScorer {

    /** BM25 参数：词频饱和系数。 */
    private static final double K1 = 1.2;
    /** BM25 参数：长度归一强度（0=不归一，1=完全归一）。 */
    private static final double B = 0.75;

    private KeywordScorer() {
    }

    /** 打分：只返回命中数 &gt; 0 的切片。 */
    public static Map<Long, Double> score(List<KbChunk> chunks, String query) {
        Map<Long, Double> out = new HashMap<>();
        if (chunks == null || query == null || query.isBlank()) {
            return out;
        }
        List<String> qgrams = ngrams(query);
        if (qgrams.isEmpty()) {
            return out;
        }
        // 候选集统计：文档数、平均长度、每个 gram 的文档频率
        int n = 0;
        long totalLen = 0;
        Map<String, Integer> df = new HashMap<>();
        for (KbChunk c : chunks) {
            if (c == null || c.getId() == null) {
                continue;
            }
            String content = c.getContent() == null ? "" : c.getContent();
            n++;
            totalLen += content.length();
            for (String g : qgrams) {
                if (content.contains(g)) {
                    df.merge(g, 1, Integer::sum);
                }
            }
        }
        if (n == 0) {
            return out;
        }
        double avgdl = Math.max(1.0, (double) totalLen / n);
        Map<String, Double> idf = new HashMap<>();
        for (String g : qgrams) {
            int d = df.getOrDefault(g, 0);
            idf.put(g, Math.log(1.0 + (n - d + 0.5) / (d + 0.5)));
        }
        for (KbChunk c : chunks) {
            if (c == null || c.getId() == null) {
                continue;
            }
            String content = c.getContent() == null ? "" : c.getContent();
            double dl = Math.max(1, content.length());
            double norm = K1 * (1.0 - B + B * dl / avgdl);
            double sum = 0.0;
            boolean any = false;
            for (String g : qgrams) {
                int f = occurrences(content, g);
                if (f <= 0) {
                    continue;
                }
                any = true;
                sum += idf.getOrDefault(g, 0.0) * (f * (K1 + 1.0)) / (f + norm);
            }
            if (any) {
                out.put(c.getId(), sum);
            }
        }
        return out;
    }

    /**
     * 子串出现次数，**非重叠**计数：每命中一次就把游标推到匹配串之后。
     *
     * <p>旧注释写「2-gram 场景下与滑窗计数等价」不成立（B5）——「aa」在「aaa」里
     * 非重叠是 1、滑窗是 2。这里刻意用非重叠：tf 要的是「这段文字里出现了几次这个词」，
     * 滑窗会把同一处重复算两次（重叠匹配在自然语言里几乎只出现在叠字上）。</p>
     */
    static int occurrences(String content, String gram) {
        if (gram.isEmpty()) {
            return 0;
        }
        int count = 0;
        int from = 0;
        while (true) {
            int i = content.indexOf(gram, from);
            if (i < 0) {
                return count;
            }
            count++;
            from = i + gram.length();
        }
    }

    /** 查询词的 char 2-gram 集合（长度 ≤2 时整体作为一个词）。 */
    public static List<String> ngrams(String s) {
        List<String> out = new ArrayList<>();
        String t = s.trim();
        if (t.length() <= 2) {
            if (!t.isEmpty()) {
                out.add(t);
            }
            return out;
        }
        for (int i = 0; i + 2 <= t.length(); i++) {
            out.add(t.substring(i, i + 2));
        }
        return out;
    }
}
