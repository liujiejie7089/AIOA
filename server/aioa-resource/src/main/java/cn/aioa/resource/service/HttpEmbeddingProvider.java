package cn.aioa.resource.service;

import cn.aioa.resource.config.KbProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.extern.slf4j.Slf4j;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * HTTP 语义嵌入 provider（docs/32 决策 D2）。
 *
 * <p>为什么不把模型跑在 Java 进程里：{@code deploy/docker-compose.yml} 已经有 <b>ollama / vllm</b>
 * 两个推理服务，复用它们零新增部署；且换模型只需改配置，不动 Java 依赖（不引入 ONNX Runtime 与模型文件）。
 * 代价是每次嵌入多一跳 HTTP（入库是离线批处理，检索只嵌入 1 条 query，可接受）。</p>
 *
 * <p>协议形态由 {@code aioa.kb.embedding.format} + URL 路径共同决定，兼容三种常见端点：</p>
 * <table border="1">
 *   <tr><th>端点</th><th>请求体</th><th>响应体</th></tr>
 *   <tr><td>{@code /api/embeddings}（Ollama 旧）</td><td>{@code {"model","prompt"}}</td><td>{@code {"embedding":[...]}}</td></tr>
 *   <tr><td>{@code /api/embed}（Ollama 新）</td><td>{@code {"model","input"}}</td><td>{@code {"embeddings":[[...]]}}</td></tr>
 *   <tr><td>{@code /v1/embeddings}（OpenAI / vLLM）</td><td>{@code {"model","input"}}</td><td>{@code {"data":[{"embedding":[...]}]}}</td></tr>
 * </table>
 * 解析侧对三种响应形态都容忍（按 {@code embedding → embeddings[0] → data[0].embedding} 依次尝试），
 * 因此选错 {@code format} 通常也能读到向量；只有请求体形状不对才会 4xx。
 *
 * <p><b>失败即抛</b>（不吞异常、不返回零向量）：</p>
 * <ul>
 *   <li>HTTP 非 2xx、超时、连接失败 → {@link IllegalStateException}；</li>
 *   <li>响应里没有向量 → {@link IllegalStateException}；</li>
 *   <li>向量长度 ≠ 配置 dims → {@link IllegalStateException}（防错维向量污染 Milvus 集合，
 *       集合维度创建后不可改，写进去就是永久坏数据）。</li>
 * </ul>
 * 入库链路上 {@code KbService.embedAll} 已对单个切片做了 try/catch（失败只告警、不阻断入库），
 * 所以这里的「抛」不会让上传失败，只会让该切片暂缺向量、由回填 job 补。</p>
 */
@Slf4j
public class HttpEmbeddingProvider implements EmbeddingProvider {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final KbProperties.Embedding cfg;
    private final HttpClient http;
    private final String name;
    private final boolean ollamaLegacy;

    public HttpEmbeddingProvider(KbProperties.Embedding cfg) {
        this.cfg = cfg;
        if (cfg.getUrl() == null || cfg.getUrl().isBlank()) {
            throw new IllegalStateException(
                    "aioa.kb.embedding-provider=http 但 aioa.kb.embedding.url 为空；"
                            + "请指向 Ollama（http://localhost:11434/api/embeddings）或 vLLM（http://localhost:8001/v1/embeddings）");
        }
        this.name = "http:" + cfg.getModel();
        this.ollamaLegacy = cfg.getUrl().contains("/api/embeddings");
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(Math.max(1000, cfg.getTimeoutMs())))
                .build();
    }

    @Override
    public String name() {
        return name;
    }

    @Override
    public int dims() {
        return cfg.getDims();
    }

    @Override
    public float[] embed(String text) {
        String body = buildBody(text == null ? "" : text);
        HttpRequest.Builder rb = HttpRequest.newBuilder()
                .uri(URI.create(cfg.getUrl()))
                .timeout(Duration.ofMillis(Math.max(1000, cfg.getTimeoutMs())))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
        if (cfg.getApiKey() != null && !cfg.getApiKey().isBlank()) {
            rb.header("Authorization", "Bearer " + cfg.getApiKey());
        }

        HttpResponse<String> resp;
        try {
            resp = http.send(rb.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("嵌入请求被中断：url=" + cfg.getUrl(), e);
        } catch (Exception e) {
            throw new IllegalStateException("嵌入服务不可达：url=" + cfg.getUrl() + "，原因=" + e, e);
        }
        if (resp.statusCode() / 100 != 2) {
            throw new IllegalStateException("嵌入服务返回 HTTP " + resp.statusCode()
                    + "：url=" + cfg.getUrl() + "，body=" + abbreviate(resp.body()));
        }

        float[] vec = parse(resp.body());
        int want = cfg.getDims();
        if (want > 0 && vec.length != want) {
            throw new IllegalStateException("嵌入维度不匹配：模型 " + cfg.getModel() + " 返回 " + vec.length
                    + " 维，配置 aioa.kb.embedding.dims=" + want
                    + "；请改正配置（Milvus 集合维度创建后不可改，写错就是永久坏数据）");
        }
        return vec;
    }

    /** 按 format + URL 路径决定请求体形状。 */
    private String buildBody(String text) {
        ObjectNode node = MAPPER.createObjectNode();
        node.put("model", cfg.getModel());
        boolean openai = "openai".equalsIgnoreCase(cfg.getFormat());
        if (openai) {
            node.put("input", text);
        } else if (ollamaLegacy) {
            node.put("prompt", text);
        } else {
            node.put("input", text);
        }
        return node.toString();
    }

    /** 依次尝试 embedding / embeddings[0] / data[0].embedding 三种响应形态。 */
    private float[] parse(String raw) {
        JsonNode root;
        try {
            root = MAPPER.readTree(raw);
        } catch (Exception e) {
            throw new IllegalStateException("嵌入响应不是合法 JSON：" + abbreviate(raw), e);
        }
        JsonNode vec = null;
        JsonNode single = root.get("embedding");
        if (single != null && single.isArray() && !single.isEmpty()) {
            vec = single;
        }
        if (vec == null) {
            JsonNode many = root.get("embeddings");
            if (many != null && many.isArray() && !many.isEmpty() && many.get(0).isArray()) {
                vec = many.get(0);
            }
        }
        if (vec == null) {
            JsonNode data = root.get("data");
            if (data != null && data.isArray() && !data.isEmpty()) {
                JsonNode inner = data.get(0).get("embedding");
                if (inner != null && inner.isArray() && !inner.isEmpty()) {
                    vec = inner;
                }
            }
        }
        if (vec == null) {
            throw new IllegalStateException("嵌入响应中找不到向量字段（embedding / embeddings / data[0].embedding）："
                    + abbreviate(raw));
        }
        float[] out = new float[vec.size()];
        for (int i = 0; i < vec.size(); i++) {
            out[i] = (float) vec.get(i).asDouble();
        }
        return out;
    }

    private static String abbreviate(String s) {
        if (s == null) {
            return "";
        }
        return s.length() <= 300 ? s : s.substring(0, 300) + "...(truncated)";
    }
}
