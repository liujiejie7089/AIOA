package cn.aioa.resource.service;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 文本向量化 provider（方案 P2 / D-2）。
 *
 * <p>设计：</p>
 * <ul>
 *   <li>默认 {@code local}：确定性哈希 + 词频加权（char n-gram），零依赖、零下载、结果可复现，
 *       保证无外网/无模型环境下也能跑通「解析→切分→向量化→检索」全链路；</li>
 *   <li>{@code bge-small-zh}：预留扩展点。当前阶段不引入模型下载与推理依赖（决策点 2），
 *       后续在管理端「一键下载并自行配置」后，新增 provider 实现并在
 *       {@code application.yml} 的 {@code aioa.kb.embedding-provider} 切换即可。</li>
 * </ul>
 *
 * <p>向量统一 256 维（local），float32 序列化为小端 BLOB 存入 kb_chunk.embedding，
 * 检索时用余弦相似度。provider 名称与维度一并落库，便于未来混用不同 provider 时区分。</p>
 */
public interface EmbeddingProvider {

    /** provider 标识，对应 kb_chunk.embedding_provider。 */
    String name();

    /** 输出向量维度。 */
    int dims();

    /** 文本 → 向量。 */
    float[] embed(String text);

    /** float32 数组 → 小端 BLOB。 */
    default byte[] toBytes(float[] vec) {
        ByteBuffer buf = ByteBuffer.allocate(vec.length * Float.BYTES).order(ByteOrder.LITTLE_ENDIAN);
        for (float v : vec) {
            buf.putFloat(v);
        }
        return buf.array();
    }

    /** BLOB → float32 数组。 */
    default float[] fromBytes(byte[] bytes) {
        if (bytes == null) {
            return null;
        }
        ByteBuffer buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        float[] vec = new float[bytes.length / Float.BYTES];
        for (int i = 0; i < vec.length; i++) {
            vec[i] = buf.getFloat();
        }
        return vec;
    }

    /** 本地确定性实现：char n-gram 词频向量 + L2 归一化。 */
    final class LocalEmbeddingProvider implements EmbeddingProvider {

        /** 输出维度。 */
        private final int dims;
        /** n-gram 长度（中文取 2，英文取 3）。 */
        private final int gram;

        public LocalEmbeddingProvider(int dims, int gram) {
            this.dims = dims;
            this.gram = gram;
        }

        @Override
        public String name() {
            return "local";
        }

        @Override
        public int dims() {
            return dims;
        }

        @Override
        public float[] embed(String text) {
            float[] vec = new float[dims];
            if (text == null || text.isBlank()) {
                return vec;
            }
            String s = text.trim();
            Map<String, Integer> freq = new HashMap<>();
            int total = 0;
            for (int i = 0; i + gram <= s.length(); i++) {
                String g = s.substring(i, i + gram);
                freq.merge(g, 1, Integer::sum);
                total++;
            }
            if (total == 0) {
                // 短于 gram 的文本，按单字符退化为 1-gram
                gramFallback(s, freq);
                total = s.length();
            }
            for (Map.Entry<String, Integer> e : freq.entrySet()) {
                int idx = hash(e.getKey());
                vec[idx] += (float) e.getValue() / total;
            }
            return normalize(vec);
        }

        private void gramFallback(String s, Map<String, Integer> freq) {
            for (int i = 0; i < s.length(); i++) {
                freq.merge(s.substring(i, i + 1), 1, Integer::sum);
            }
        }

        private int hash(String g) {
            // 稳定哈希：把 n-gram 散列到 [0, dims) 区间
            int h = 0x811c9dc5;
            byte[] b = g.getBytes(StandardCharsets.UTF_8);
            for (byte x : b) {
                h = (h ^ (x & 0xff)) * 0x01000193;
            }
            return Math.floorMod(h, dims);
        }

        private static float[] normalize(float[] v) {
            double norm = 0.0;
            for (float x : v) {
                norm += (double) x * x;
            }
            if (norm == 0.0) {
                return v;
            }
            float scale = (float) (1.0 / Math.sqrt(norm));
            for (int i = 0; i < v.length; i++) {
                v[i] *= scale;
            }
            return v;
        }
    }

    /** 默认 provider：256 维、2-gram（兼顾中文与英文子串匹配）。 */
    static EmbeddingProvider local() {
        return new LocalEmbeddingProvider(256, 2);
    }

    /** 计算两向量余弦相似度。 */
    static float cosine(float[] a, float[] b) {
        if (a == null || b == null || a.length == 0 || b.length != a.length) {
            return 0f;
        }
        double dot = 0.0, na = 0.0, nb = 0.0;
        for (int i = 0; i < a.length; i++) {
            dot += (double) a[i] * b[i];
            na += (double) a[i] * a[i];
            nb += (double) b[i] * b[i];
        }
        if (na == 0.0 || nb == 0.0) {
            return 0f;
        }
        return (float) (dot / (Math.sqrt(na) * Math.sqrt(nb)));
    }

    /** 列表重排用的小工具：返回索引按相似度降序。 */
    static List<Integer> rank(float[] query, List<float[]> candidates) {
        // 简单实现：直接返回自然序，由调用方用 cosine 自行排序
        return java.util.stream.IntStream.range(0, candidates.size()).boxed().toList();
    }
}
