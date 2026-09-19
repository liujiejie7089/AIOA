package cn.aioa.resource.store;

import cn.aioa.resource.entity.KbChunk;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 轻量关键词打分（原内联在 {@code MysqlKnowledgeStore#bm25}，docs/32 Ph3 抽公共）。
 *
 * <p>打分口径：查询词的 char 2-gram 覆盖切片正文的比例 × 命中长度惩罚 {@code (1 + ln(1+hit))}。
 * 这不是严格的 BM25（无 IDF、无文档长度归一），但它**确定、可复现、零依赖**，
 * 且对中文短查询效果稳定——与 Milvus 原生 BM25 并存时，作为「服务端不支持 BM25」的兜底腿。</p>
 *
 * <p>抽出来的原因与 {@link RrfFusion} 相同：两种 store 的兜底路径必须口径一致。</p>
 */
public final class KeywordScorer {

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
        for (KbChunk c : chunks) {
            if (c.getId() == null) {
                continue;
            }
            String content = c.getContent() == null ? "" : c.getContent();
            int hit = 0;
            for (String g : qgrams) {
                if (content.contains(g)) {
                    hit++;
                }
            }
            if (hit > 0) {
                out.put(c.getId(), (double) hit / qgrams.size() * (1.0 + Math.log1p(hit)));
            }
        }
        return out;
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
