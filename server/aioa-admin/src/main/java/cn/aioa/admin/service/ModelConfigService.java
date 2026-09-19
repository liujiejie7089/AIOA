package cn.aioa.admin.service;

import cn.aioa.admin.entity.ModelConfig;
import cn.aioa.admin.mapper.ModelConfigMapper;
import cn.aioa.admin.support.ModelKeyCodec;
import cn.aioa.common.exception.BizException;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 模型配置服务：管理端 CRUD + 变更后向 agent 推送热加载（/internal/v1/models/apply）。
 * 推送失败不影响配置保存（agent 下线场景），agent 恢复后管理端再次保存即可同步。
 *
 * <p>V61「手动添加模型」：新增大模型类型预设、API Key 加密落库、连通性校验、启停闸门。
 */
@Slf4j
@Service
public class ModelConfigService {

    /** 连通性校验超时：足够覆盖一次真实握手，又不至于让管理端按钮一直转圈。 */
    private static final Duration CHECK_TIMEOUT = Duration.ofSeconds(15);

    private static final List<ModelPreset> PRESETS = List.of(
            new ModelPreset("minimax", "MiniMax", "https://api.minimax.chat/v1", "MiniMax-Text-01",
                    "MINIMAX_API_KEY", new BigDecimal("0.30"), 200000),
            new ModelPreset("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-chat",
                    "DEEPSEEK_API_KEY", new BigDecimal("0.30"), 65536),
            new ModelPreset("dashscope", "阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "qwen-plus", "DASHSCOPE_API_KEY", new BigDecimal("0.30"), 131072),
            new ModelPreset("vllm", "vLLM 私有部署", "http://127.0.0.1:8001/v1", "Qwen2.5-7B-Instruct",
                    "VLLM_API_KEY", new BigDecimal("0.30"), 32768),
            new ModelPreset("ollama", "Ollama 本地", "http://127.0.0.1:11434/v1", "qwen2.5:7b",
                    "OLLAMA_API_KEY", new BigDecimal("0.30"), 32768),
            new ModelPreset("echo", "回声（演示兜底）", "internal://echo", "echo",
                    "ECHO_API_KEY", new BigDecimal("0.30"), 0),
            new ModelPreset("custom", "自定义（OpenAI 兼容）", "", "", "", new BigDecimal("0.30"), 0));

    private final ModelConfigMapper mapper;
    private final ObjectMapper objectMapper;
    private final ModelKeyCodec keyCodec;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    @Value("${aioa.agent.base-url:http://127.0.0.1:8000}")
    private String agentBaseUrl;

    public ModelConfigService(ModelConfigMapper mapper, ObjectMapper objectMapper, ModelKeyCodec keyCodec) {
        this.mapper = mapper;
        this.objectMapper = objectMapper;
        this.keyCodec = keyCodec;
    }

    // ---------- 读取 ----------

    public List<ModelConfig> list() {
        return mapper.selectList(new LambdaQueryWrapper<ModelConfig>()
                .orderByDesc(ModelConfig::getIsDefault)
                .orderByAsc(ModelConfig::getSort));
    }

    /** 列表给前端：只回掩码，不带明文 Key；agent 侧「是否已配置」整列表只问一次。 */
    public List<ModelConfigView> listViews() {
        Set<String> configured = agentConfiguredKeys();
        return list().stream().map(c -> toView(c, configured)).toList();
    }

    public List<ModelPreset> presets() {
        return PRESETS;
    }

    public String defaultKey() {
        ModelConfig d = mapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getIsDefault, true)
                .last("limit 1"));
        return d == null ? ModelConfig.DEFAULT_KEY : d.getProviderKey();
    }

    private ModelConfigView toView(ModelConfig cfg) {
        return toView(cfg, agentConfiguredKeys());
    }

    /**
     * 密钥来源判定以**运行时**为准：管理端填写 > 本进程环境变量 > agent 侧已加载的同名环境变量。
     * 最后一条很关键 —— 服务端容器常常没有供应商 Key，但 agent 有，此时显示「未配置」是错的。
     */
    private ModelConfigView toView(ModelConfig cfg, Set<String> agentConfigured) {
        String plain = keyCodec.decrypt(cfg.getApiKey());
        if (plain != null && !plain.isBlank()) {
            return ModelConfigView.of(cfg, plain, ModelConfigView.SOURCE_DB);
        }
        String envKey = readEnvKey(cfg.getApiKeyEnv());
        if (!envKey.isBlank()) {
            return ModelConfigView.of(cfg, envKey, ModelConfigView.SOURCE_ENV);
        }
        if (agentConfigured.contains(cfg.getProviderKey())) {
            return ModelConfigView.of(cfg, null, ModelConfigView.SOURCE_ENV);
        }
        return ModelConfigView.of(cfg, null, ModelConfigView.SOURCE_NONE);
    }

    /** 问 agent 哪些 provider 已经拿到 Key（密钥只回「是否配置」，不回值）。 */
    private Set<String> agentConfiguredKeys() {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentBaseUrl + "/internal/v1/models"))
                    .timeout(Duration.ofSeconds(3))
                    .GET()
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) {
                return Set.of();
            }
            JsonNode providers = objectMapper.readTree(resp.body()).path("providers");
            Set<String> out = new LinkedHashSet<>();
            for (JsonNode node : providers) {
                if ("yes".equalsIgnoreCase(node.path("api_key_configured").asText(""))) {
                    out.add(node.path("key").asText(""));
                }
            }
            return out;
        } catch (Exception e) {
            return Set.of();
        }
    }

    private static String readEnvKey(String envName) {
        if (envName == null || envName.isBlank()) {
            return "";
        }
        String v = System.getenv(envName);
        return v == null ? "" : v.trim();
    }

    /** 实际生效的 Key：管理端填写的优先，其次环境变量。 */
    private String effectiveKey(ModelConfig cfg) {
        String plain = keyCodec.decrypt(cfg.getApiKey());
        if (plain != null && !plain.isBlank()) {
            return plain;
        }
        return readEnvKey(cfg.getApiKeyEnv());
    }

    // ---------- 写入 ----------

    public ModelConfigView upsert(ModelConfig cfg, Long operatorId) {
        LocalDateTime now = LocalDateTime.now();
        ModelConfig existing = mapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getProviderKey, cfg.getProviderKey()));

        // 前端回传的是掩码（列表里只有掩码），掩码原样带回意味着「不修改密钥」。
        String submitted = cfg.getApiKey();
        if (isMaskedValue(submitted)) {
            cfg.setApiKey(existing == null ? null : existing.getApiKey());
        } else {
            cfg.setApiKey(keyCodec.encrypt(submitted));
        }

        if (existing == null) {
            cfg.setCreatedAt(now);
            cfg.setCreatedBy(operatorId);
            if (cfg.getSort() == null) {
                cfg.setSort(100);
            }
            if (isBlank(cfg.getProviderType())) {
                ModelPreset preset = presetOf(cfg.getProviderKey());
                cfg.setProviderType(preset != null ? preset.type() : "custom");
            }
            mapper.insert(cfg);
        } else {
            cfg.setId(existing.getId());
            cfg.setUpdatedAt(now);
            cfg.setCreatedAt(existing.getCreatedAt());
            cfg.setCreatedBy(existing.getCreatedBy());
            if (isBlank(cfg.getProviderType())) {
                cfg.setProviderType(isBlank(existing.getProviderType()) ? "custom" : existing.getProviderType());
            }
            mapper.updateById(cfg);
        }
        if (Boolean.TRUE.equals(cfg.getIsDefault())) {
            clearOthers(cfg.getProviderKey());
        }
        push();
        return toView(cfg);
    }

    /**
     * 掩码判定：列表只返回掩码，管理员打开编辑再保存时如果没动密钥，回传的就是掩码，
     * 此时必须保持库里的密文不变，否则会把真实密钥覆盖成 "****"。
     */
    private static boolean isMaskedValue(String v) {
        return v != null && v.contains("****");
    }

    public void delete(String providerKey) {
        mapper.delete(new LambdaQueryWrapper<ModelConfig>().eq(ModelConfig::getProviderKey, providerKey));
        push();
    }

    public void setDefault(String providerKey) {
        ModelConfig target = mapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getProviderKey, providerKey));
        if (target == null) {
            throw BizException.notFound("模型不存在：" + providerKey);
        }
        clearOthers(providerKey);
        ModelConfig patch = new ModelConfig();
        patch.setId(target.getId());
        patch.setIsDefault(true);
        patch.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(patch);
        push();
    }

    /**
     * 启停：启用前先做连通性校验，不通过则**保持原状态**并抛出明确原因；
     * 停用不校验（避免因为供应商临时故障而无法停用）。
     */
    public CheckResult setStatus(String providerKey, boolean enabled) {
        ModelConfig cfg = require(providerKey);
        if (!enabled) {
            setEnabled(cfg, false);
            return new CheckResult(providerKey, true, "已停用（停用不做连通性校验）", 0L);
        }
        CheckResult result = check(providerKey);
        if (!result.ok()) {
            throw BizException.badRequest("启用失败，模型仍保持停用：" + result.message());
        }
        setEnabled(cfg, true);
        return new CheckResult(providerKey, true, "已启用（连通性校验通过，耗时 " + result.latencyMs() + "ms）",
                result.latencyMs());
    }

    private void setEnabled(ModelConfig cfg, boolean enabled) {
        ModelConfig patch = new ModelConfig();
        patch.setId(cfg.getId());
        patch.setEnabled(enabled);
        patch.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(patch);
        cfg.setEnabled(enabled);
        push();
    }

    // ---------- 连通性校验 ----------

    /**
     * 连通性校验：**委托 agent 执行**（POST /internal/v1/models/check）。
     *
     * 为什么不在这里直接打供应商：服务端容器通常没有供应商 Key（Key 配在 agent 侧），
     * 由本进程直接探测会把「本进程没配 Key」误报成「模型连不通」。
     * 校验前先 push 一次，确保 agent 用的是最新配置（含刚填写的 Key）。
     */
    public CheckResult check(String providerKey) {
        ModelConfig cfg = require(providerKey);
        if (isInternal(cfg)) {
            return new CheckResult(providerKey, true, "回声模型为本地兜底实现，无需联网校验", 0L);
        }
        push();
        long start = System.currentTimeMillis();
        try {
            String body = "{\"key\":" + quote(providerKey) + "}";
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentBaseUrl + "/internal/v1/models/check"))
                    .header("Content-Type", "application/json")
                    .timeout(CHECK_TIMEOUT)
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            long cost = System.currentTimeMillis() - start;
            if (resp.statusCode() != 200) {
                return new CheckResult(providerKey, false,
                        "连通性校验失败：agent 返回 HTTP " + resp.statusCode(), cost);
            }
            JsonNode data = objectMapper.readTree(resp.body());
            boolean ok = data.path("ok").asBoolean(false);
            long latency = data.path("latency_ms").asLong(cost);
            String message = data.path("message").asText("");
            return new CheckResult(providerKey, ok, message, latency);
        } catch (Exception e) {
            return new CheckResult(providerKey, false,
                    "连通性校验未执行：agent 不可达（" + agentBaseUrl + "）——" + nullToEmpty(e.getMessage()),
                    System.currentTimeMillis() - start);
        }
    }

    private static boolean isInternal(ModelConfig cfg) {
        String base = cfg.getBaseUrl() == null ? "" : cfg.getBaseUrl();
        return "echo".equals(cfg.getProviderKey()) || base.startsWith("internal://");
    }

    // ---------- 推送 agent ----------

    private void clearOthers(String keepKey) {
        mapper.update(null, new LambdaUpdateWrapper<ModelConfig>()
                .ne(ModelConfig::getProviderKey, keepKey)
                .set(ModelConfig::getIsDefault, false));
    }

    private ModelConfig require(String providerKey) {
        ModelConfig cfg = mapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getProviderKey, providerKey));
        if (cfg == null) {
            throw BizException.notFound("模型不存在：" + providerKey);
        }
        return cfg;
    }

    /** 把当前配置全量推给 agent 热加载；失败仅告警。 */
    public void push() {
        try {
            List<ModelConfig> all = list();
            List<Map<String, Object>> models = all.stream().map(m -> {
                Map<String, Object> o = new LinkedHashMap<>();
                o.put("key", m.getProviderKey());
                o.put("providerType", m.getProviderType());
                o.put("baseUrl", m.getBaseUrl());
                o.put("model", m.getModelName());
                o.put("apiKeyEnv", m.getApiKeyEnv());
                // 明文仅在内网推送链路上出现（127.0.0.1:8000），不落盘、不回前端
                o.put("apiKey", effectiveKey(m));
                o.put("temperature", m.getTemperature() == null ? null : m.getTemperature().doubleValue());
                o.put("maxContext", m.getMaxContext() == null ? 0 : m.getMaxContext());
                o.put("enabled", Boolean.TRUE.equals(m.getEnabled()));
                o.put("isDefault", Boolean.TRUE.equals(m.getIsDefault()));
                return o;
            }).toList();
            String body = objectMapper.writeValueAsString(Map.of("models", models, "default", defaultKey()));
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentBaseUrl + "/internal/v1/models/apply"))
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(5))
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            log.info("model config pushed to agent: {} entries, agent status={}", models.size(), resp.statusCode());
        } catch (Exception e) {
            log.warn("push model config to agent failed (agent offline?): {}", e.getMessage());
        }
    }

    private static String quote(String s) {
        return "\"" + String.valueOf(s).replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    /** 连通性校验结果：ok=false 时 message 是给用户看的明确原因。 */
    public record CheckResult(String providerKey, boolean ok, String message, long latencyMs) {
    }

    /** 新增模型的类型预设：选中后自动带出接入地址/模型名/密钥环境变量名。 */
    public record ModelPreset(String type, String label, String baseUrl, String defaultModel,
                              String apiKeyEnv, BigDecimal temperature, Integer maxContext) {
    }

    /** 密钥保护强度提示：未配置专用加密键时前端给出告警。 */
    public boolean isKeyEncryptionWeak() {
        return keyCodec.isUsingFallback();
    }

    /** 供校验前预览：把预设按 type 索引，供控制器回填缺省值。 */
    public ModelPreset presetOf(String type) {
        String t = type == null ? "" : type.toLowerCase(Locale.ROOT);
        return PRESETS.stream().filter(p -> p.type().equals(t)).findFirst().orElse(null);
    }
}
