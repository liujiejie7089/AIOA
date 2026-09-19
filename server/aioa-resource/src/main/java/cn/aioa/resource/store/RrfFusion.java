package cn.aioa.resource.store;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * RRF（Reciprocal Rank Fusion）融合工具（原内联在 {@code MysqlKnowledgeStore}，docs/32 Ph3 抽公共）。
 *
 * <p>只按**排名**融合，规避「关键词覆盖率」与「余弦相似度」两个分数数量纲不一致、不可直接加权的问题。
 * 常数 {@link #RRF_K} = 60（Elasticsearch 生产默认值）。</p>
 *
 * <p>抽出来的原因：Milvus 档位在「服务端不支持原生 BM25」时需要退回**客户端融合**，
 * 此时必须与 MySQL 档位用**完全同一套融合口径**，否则两种 store 的排序无法对齐（Ph3 验收项）。</p>
 */
public final class RrfFusion {

    /** RRF 融合常数（Elasticsearch 生产默认）。 */
    public static final double RRF_K = 60.0;

    private RrfFusion() {
    }

    /** 按分数降序返回主键序列（用于喂给 {@link #add}）。 */
    public static List<Long> rankBy(Map<Long, Double> scores) {
        return scores.entrySet().stream()
                .sorted(Map.Entry.<Long, Double>comparingByValue().reversed())
                .map(Map.Entry::getKey)
                .toList();
    }

    /** 把一路召回的排名累加进融合分（1 / (k + rank)）。 */
    public static void add(Map<Long, Double> fused, List<Long> ranked) {
        for (int i = 0; i < ranked.size(); i++) {
            fused.merge(ranked.get(i), 1.0 / (RRF_K + i + 1), Double::sum);
        }
    }

    /** 多路召回一次性融合：每路先按分排序再加权累加。 */
    public static Map<Long, Double> fuse(List<Map<Long, Double>> legs) {
        Map<Long, Double> fused = new HashMap<>();
        if (legs != null) {
            for (Map<Long, Double> leg : legs) {
                if (leg != null && !leg.isEmpty()) {
                    add(fused, rankBy(leg));
                }
            }
        }
        return fused;
    }

    /** 按融合分降序取前 n 个主键。 */
    public static List<Long> topK(Map<Long, Double> fused, int n) {
        List<Long> all = rankBy(fused);
        return all.size() <= n ? all : new ArrayList<>(all.subList(0, n));
    }
}
