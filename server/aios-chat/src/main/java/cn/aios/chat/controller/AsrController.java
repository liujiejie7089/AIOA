package cn.aios.chat.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.http.AgentHttpClient;
import cn.aios.common.resp.ApiResponse;
import cn.aios.security.AuthUserContext;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 语音输入（ASR）。
 *
 * <pre>
 *   POST /api/v1/asr/transcribe?lang=zh   body = 音频原始字节（Content-Type: audio/webm）
 *   GET  /api/v1/asr/status               诊断：agent 侧模型能不能用
 * </pre>
 *
 * <p><b>为什么录音不在这里</b>：麦克风只有用户手机上的浏览器（getUserMedia）能拿到，
 * 服务端进程永远碰不到；后端只负责把「已经录好的音频」转成文字。故本端点收的是音频字节。</p>
 *
 * <p><b>为什么转发到 agent</b>：模型运行在 Python agent 里；H5 只认同源 {@code /api/*}，
 * 不能直连 agent 的 :8000（未对浏览器暴露，且要另做 CORS/鉴权）。
 * 与 {@code ModelConfigService} → {@code /internal/v1/models} 是同一套模式。</p>
 *
 * <p><b>失败一律报错，不静默</b>：agent 不可达 / 模型未就绪 → 明确 503，
 * 绝不放行成「识别为空」让用户以为是自己没说清。</p>
 */
@Tag(name = "语音输入")
@RestController
@RequestMapping("/api/v1/asr")
public class AsrController {

    @Value("${aios.agent.base-url:http://localhost:8000}")
    private String agentBaseUrl;

    @Value("${aios.asr.enabled:true}")
    private boolean enabled;

    @Value("${aios.asr.agent-path:/internal/v1/asr/transcribe}")
    private String transcribePath;

    @Value("${aios.asr.status-path:/internal/v1/asr/status}")
    private String statusPath;

    /** 单次音频上限（字节）。与 agent 侧 AIOS_ASR_MAX_BYTES 同义，改一处要同时改。 */
    @Value("${aios.asr.max-bytes:10485760}")
    private long maxBytes;

    private static final Logger log = LoggerFactory.getLogger(AsrController.class);

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final HttpClient http = AgentHttpClient.agentBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    /** 服务间令牌：agent 的 `/internal/v1/*` 已强制校验（2026-10-18），无票直接 401。 */
    private final cn.aios.security.ServiceTokenProvider serviceTokenProvider;

    public AsrController(cn.aios.security.ServiceTokenProvider serviceTokenProvider) {
        this.serviceTokenProvider = serviceTokenProvider;
    }

    @Operation(summary = "语音转文字：上传音频字节，返回识别文本")
    @PostMapping("/transcribe")
    public ApiResponse<Map<String, Object>> transcribe(
            @RequestBody(required = false) byte[] audio,
            @RequestHeader(value = "Content-Type", required = false) String contentType,
            @RequestParam(value = "lang", required = false, defaultValue = "zh") String lang) throws Exception {

        // /api/** 已由 SecurityConfig 要求登录，这里再取一次用户，语义与其它端点一致
        AuthUserContext.require();
        if (!enabled) {
            throw new BizException(503, "语音输入未开启");
        }
        if (audio == null || audio.length == 0) {
            throw BizException.badRequest("音频为空");
        }
        if (audio.length > maxBytes) {
            throw new BizException(413, "音频超过 " + (maxBytes / 1024 / 1024) + "MB");
        }
        String ctype = (contentType == null || contentType.isBlank())
                ? "audio/webm" : contentType.split(";")[0].trim();

        JsonNode root = callAgent(transcribePath + "?lang=" + URLEncoder.encode(lang, StandardCharsets.UTF_8),
                ctype, audio);
        JsonNode data = root.path("data");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("text", data.path("text").asText(""));
        out.put("lang", data.path("lang").asText(lang));
        out.put("durationMs", data.path("durationMs").asLong(0));
        out.put("model", data.path("model").asText(""));
        return ApiResponse.ok(out);
    }

    @Operation(summary = "语音输入诊断：模型是否就绪（不伪装可用）")
    @GetMapping("/status")
    public ApiResponse<Map<String, Object>> status() throws Exception {
        AuthUserContext.require();
        JsonNode root = callAgent(statusPath, null, null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("enabled", enabled);
        out.put("agent", agentBaseUrl);
        for (String k : new String[]{"engine", "model", "device", "available", "error"}) {
            JsonNode v = root.path(k);
            if (v.isMissingNode()) {
                continue;
            }
            if (v.isNull()) {
                out.put(k, null);
            } else if (v.isBoolean()) {
                out.put(k, v.asBoolean());
            } else {
                out.put(k, v.asText());
            }
        }
        return ApiResponse.ok(out);
    }

    /** 调 agent 的内部端点；非 200 或 code!=0 统一翻成业务异常（含 agent 不可达）。 */
    private JsonNode callAgent(String pathAndQuery, String contentType, byte[] body) throws Exception {
        HttpRequest.Builder b = HttpRequest.newBuilder()
                .uri(URI.create(agentBaseUrl + pathAndQuery))
                .header("Authorization", "Bearer "
                        + serviceTokenProvider.generate(cn.aios.security.ServiceTokenProvider.SVC_SERVER))
                .timeout(Duration.ofSeconds(120));
        if (contentType != null) {
            b.header("Content-Type", contentType);
        }
        HttpRequest req = (body == null
                ? b.GET()
                : b.POST(HttpRequest.BodyPublishers.ofByteArray(body))).build();

        HttpResponse<String> resp;
        try {
            resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (Exception e) {
            // 内部地址属拓扑信息，只进日志；回给用户的必须是人话
            log.warn("asr agent unreachable: {} ({})", agentBaseUrl + pathAndQuery, e.toString());
            throw new BizException(503, "语音识别服务不可用，请稍后重试");
        }

        String raw = resp.body() == null ? "{}" : resp.body();
        JsonNode root = objectMapper.readTree(raw);
        if (resp.statusCode() != 200) {
            throw new BizException(resp.statusCode(), root.path("message").asText("语音识别失败"));
        }
        if (root.has("code") && root.path("code").asInt(-1) != 0) {
            throw new BizException(502, root.path("message").asText("语音识别失败"));
        }
        return root;
    }
}
