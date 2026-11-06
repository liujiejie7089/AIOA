package cn.aios.chat.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.error.ErrorCode;
import cn.aios.security.AuthUserContext;
import cn.aios.security.AuthUser;
import cn.aios.security.ServiceTokenProvider;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * ASR 转发链路的**失败表达**（B7）。
 *
 * <p>原实现把 {@code objectMapper.readTree(raw)} 写在状态码判断之前、且没有 try ——
 * agent 被网关/反代挡回 HTML 时 Jackson 抛 {@code JsonParseException}，
 * 用户拿到 500（而且栈里是解析错误，看不出是「服务不可用」），
 * 与类注释声明的「失败一律明确 503」相反。</p>
 *
 * <p>这里用 JDK 自带 {@link HttpServer} 起一个假 agent，分别回 HTML 错误页 / JSON 错误 /
 * 正常 JSON，验证三种形态各自落到该落的出口。</p>
 */
class AsrControllerTest {

    private HttpServer agent;
    private AsrController controller;

    @BeforeEach
    void setUp() throws Exception {
        ServiceTokenProvider tokens = mock(ServiceTokenProvider.class);
        when(tokens.generate(anyString())).thenReturn("svc-token");
        controller = new AsrController(tokens);
        // @Value 字段在纯单元测试里不会被注入，显式补齐（否则 URI 拼出 "...null"）
        set(controller, "statusPath", "/internal/v1/asr/status");
        set(controller, "transcribePath", "/internal/v1/asr/transcribe");
        set(controller, "enabled", true);
        set(controller, "maxBytes", 10L * 1024 * 1024);
        AuthUserContext.set(AuthUser.of(1L, 7L, "test", "测试账号", List.of()));
    }

    @AfterEach
    void tearDown() {
        AuthUserContext.clear();
        if (agent != null) {
            agent.stop(0);
            agent = null;
        }
    }

    /** 起一个假 agent：/internal/v1/asr/status 固定按给定状态码与 body 回。 */
    private void startAgent(int status, String body, String contentType) throws Exception {
        agent = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        agent.createContext("/internal/v1/asr/status", ex -> {
            byte[] out = body.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", contentType);
            ex.sendResponseHeaders(status, out.length == 0 ? -1 : out.length);
            if (out.length > 0) {
                ex.getResponseBody().write(out);
            }
            ex.close();
        });
        agent.start();
        set(controller, "agentBaseUrl", "http://127.0.0.1:" + agent.getAddress().getPort());
    }

    private static void set(Object target, String field, Object value) throws Exception {
        Field f = target.getClass().getDeclaredField(field);
        f.setAccessible(true);
        f.set(target, value);
    }

    @Test
    @DisplayName("网关挡回 HTML 错误页（502 + HTML）⇒ 上游错误码 + 人话，不是 500 解析异常")
    void htmlErrorPageBecomes503() throws Exception {
        startAgent(502, "<html><body><h1>502 Bad Gateway</h1></body></html>", "text/html");
        BizException e = assertThrows(BizException.class, () -> controller.status());
        // 码值口径：BizException(503) 会被 ErrorCode.ofCode 映射成 MODEL_UPSTREAM_ERROR(502)
        // —— 这是错误码体系的既有约定（5xx 统一上游错误），不是本处修复引入的。
        // 关键在于：这里抛的是**业务异常 + 人话**，而不是 Jackson 的 JsonParseException（500）。
        assertEquals(ErrorCode.MODEL_UPSTREAM_ERROR.code(), e.getCode());
        assertTrue(e.getMessage().contains("语音识别服务不可用"), e.getMessage());
    }

    @Test
    @DisplayName("状态码 200 但 body 不是 JSON ⇒ 上游错误码，且不能 NPE")
    void nonJson200Becomes503() throws Exception {
        startAgent(200, "OK", "text/plain");
        BizException e = assertThrows(BizException.class, () -> controller.status());
        assertEquals(ErrorCode.MODEL_UPSTREAM_ERROR.code(), e.getCode());
        assertTrue(e.getMessage().contains("语音识别服务不可用"), e.getMessage());
    }

    @Test
    @DisplayName("空 body ⇒ 上游错误码（不是「识别为空」也不是 NPE）")
    void emptyBodyBecomes503() throws Exception {
        startAgent(200, "", "application/json");
        BizException e = assertThrows(BizException.class, () -> controller.status());
        assertEquals(ErrorCode.MODEL_UPSTREAM_ERROR.code(), e.getCode());
    }

    @Test
    @DisplayName("上游是 JSON 错误时仍透传状态码与原话（不降级成 503 把信息吃掉）")
    void jsonErrorKeepsUpstreamStatusAndMessage() throws Exception {
        startAgent(502, "{\"message\":\"ASR 模型未就绪\"}", "application/json");
        BizException e = assertThrows(BizException.class, () -> controller.status());
        assertEquals(502, e.getCode(), "能解析就把上游状态码透传出去");
        assertTrue(e.getMessage().contains("ASR 模型未就绪"), e.getMessage());
    }

    @Test
    @DisplayName("正常 JSON ⇒ 不抛，按字段回（含 available）")
    void healthyJsonPasses() throws Exception {
        startAgent(200, "{\"engine\":\"funasr\",\"model\":\"paraformer\",\"available\":true}",
                "application/json");
        var res = assertDoesNotThrow(() -> controller.status());
        assertNotNull(res);
        assertNotNull(res.getData(), "必须带回数据");
        assertEquals("funasr", res.getData().get("engine"));
        assertEquals(Boolean.TRUE, res.getData().get("available"));
    }
}
