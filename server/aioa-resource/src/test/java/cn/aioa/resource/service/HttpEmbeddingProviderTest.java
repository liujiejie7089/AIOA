package cn.aioa.resource.service;

import cn.aioa.resource.config.KbProperties;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * HTTP 嵌入 provider 单测（docs/32 Ph1）。
 *
 * <p>用一个 JDK 内置的 {@code com.sun.net.httpserver} 桩服务替掉 Ollama / vLLM，
 * 覆盖三种端点形状 + 三条失败路径。**不需要真模型、不需要外网**，
 * 但足以钉死「请求体形状 / 响应解析 / 维度校验 / 失败即抛」这四件最容易出错的事。</p>
 */
class HttpEmbeddingProviderTest {

    private HttpServer server;
    private int port;
    private volatile String lastBody = "";
    private volatile int status = 200;
    private volatile String body = "{\"embedding\":[0.1,0.2,0.3]}";

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", ex -> {
            lastBody = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            byte[] out = body.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
            ex.sendResponseHeaders(status, out.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(out);
            }
        });
        server.start();
        port = server.getAddress().getPort();
    }

    @AfterEach
    void stop() {
        if (server != null) {
            server.stop(0);
        }
    }

    private KbProperties.Embedding cfg(String path, String format, int dims) {
        KbProperties.Embedding e = new KbProperties.Embedding();
        e.setUrl("http://127.0.0.1:" + port + path);
        e.setFormat(format);
        e.setModel("bge-small-zh-v1.5");
        e.setDims(dims);
        e.setTimeoutMs(5000);
        return e;
    }

    @Test
    @DisplayName("Ollama 旧端点 /api/embeddings：请求发 prompt，响应读 embedding")
    void ollamaLegacyShape() {
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/api/embeddings", "ollama", 3));
        float[] v = p.embed("年度预算");
        assertArrayEquals(new float[]{0.1f, 0.2f, 0.3f}, v, 1e-6f);
        assertTrue(lastBody.contains("\"prompt\""), "旧端点应发 prompt 字段，实际=" + lastBody);
        assertTrue(lastBody.contains("bge-small-zh-v1.5"));
    }

    @Test
    @DisplayName("Ollama 新端点 /api/embed：请求发 input，响应读 embeddings[0]")
    void ollamaNewShape() {
        body = "{\"embeddings\":[[0.5,0.6,0.7]]}";
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/api/embed", "ollama", 3));
        float[] v = p.embed("年度预算");
        assertArrayEquals(new float[]{0.5f, 0.6f, 0.7f}, v, 1e-6f);
        assertTrue(lastBody.contains("\"input\""), "新端点应发 input 字段，实际=" + lastBody);
    }

    @Test
    @DisplayName("OpenAI 兼容端点 /v1/embeddings：请求发 input，响应读 data[0].embedding")
    void openAiShape() {
        body = "{\"object\":\"list\",\"data\":[{\"index\":0,\"embedding\":[1.0,2.0,3.0]}]}";
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/v1/embeddings", "openai", 3));
        float[] v = p.embed("年度预算");
        assertArrayEquals(new float[]{1.0f, 2.0f, 3.0f}, v, 1e-6f);
        assertTrue(lastBody.contains("\"input\""), "OpenAI 形态应发 input 字段，实际=" + lastBody);
    }

    @Test
    @DisplayName("维度不匹配必须失败：写错维度的向量进 Milvus 就是永久坏数据")
    void dimsMismatchFailsFast() {
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/api/embeddings", "ollama", 512));
        IllegalStateException ex = assertThrows(IllegalStateException.class, () -> p.embed("年度预算"));
        assertTrue(ex.getMessage().contains("维度不匹配"), ex.getMessage());
    }

    @Test
    @DisplayName("HTTP 非 2xx 必须失败（不吞异常返回零向量）")
    void httpErrorFailsFast() {
        status = 500;
        body = "{\"error\":\"model not found\"}";
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/api/embeddings", "ollama", 3));
        IllegalStateException ex = assertThrows(IllegalStateException.class, () -> p.embed("x"));
        assertTrue(ex.getMessage().contains("HTTP 500"), ex.getMessage());
    }

    @Test
    @DisplayName("响应里找不到向量字段必须失败")
    void missingVectorFailsFast() {
        body = "{\"ok\":true}";
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/api/embeddings", "ollama", 3));
        IllegalStateException ex = assertThrows(IllegalStateException.class, () -> p.embed("x"));
        assertTrue(ex.getMessage().contains("找不到向量字段"), ex.getMessage());
    }

    @Test
    @DisplayName("非 JSON 响应必须失败并保留响应片段，便于定位（如反代返回的 HTML 错误页）")
    void nonJsonFailsFast() {
        body = "<html>502 Bad Gateway</html>";
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/api/embeddings", "ollama", 3));
        IllegalStateException ex = assertThrows(IllegalStateException.class, () -> p.embed("x"));
        assertTrue(ex.getMessage().contains("不是合法 JSON"), ex.getMessage());
    }

    @Test
    @DisplayName("url 为空直接拒绝构造（不要留到调用时才炸）")
    void blankUrlRejected() {
        KbProperties.Embedding e = cfg("/api/embeddings", "ollama", 3);
        e.setUrl("");
        assertThrows(IllegalStateException.class, () -> new HttpEmbeddingProvider(e));
    }

    @Test
    @DisplayName("provider 标识带模型名（落库到 kb_chunk.embedding_provider，便于按 provider 重算）")
    void providerNameCarriesModel() {
        HttpEmbeddingProvider p = new HttpEmbeddingProvider(cfg("/api/embeddings", "ollama", 3));
        assertEquals("http:bge-small-zh-v1.5", p.name());
        assertEquals(3, p.dims());
    }
}
