package cn.aios.admin.service;

import cn.aios.admin.entity.ModelConfig;
import cn.aios.admin.entity.ModelConfigSnapshot;
import cn.aios.admin.mapper.ModelConfigMapper;
import cn.aios.admin.mapper.ModelConfigSnapshotMapper;
import cn.aios.admin.support.ModelKeyCodec;
import cn.aios.common.exception.BizException;
import cn.aios.common.http.AgentHttpClient;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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
            // 2026-11-04：候选里原来的 MiniMax-Text-01 / MiniMax-M1 / abab6.5s-chat 已被厂商下线
            // （实测 /models 对这三个都回 404 not_found_error），新手照候选填就会在第一次对话里炸。
            // 这里换成本账号 /models 当前真实返回的 9 个模型，并用最新的 MiniMax-M3.1-Flash 作默认。
            new ModelPreset("minimax", "MiniMax", "https://api.minimax.chat/v1", "MiniMax-M3.1-Flash",
                    "MINIMAX_API_KEY", new BigDecimal("0.30"), 200000,
                    List.of("MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed",
                            "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1",
                            "MiniMax-M2.1-highspeed", "MiniMax-M2")),
            new ModelPreset("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-chat",
                    "DEEPSEEK_API_KEY", new BigDecimal("0.30"), 65536,
                    List.of("deepseek-chat", "deepseek-reasoner")),
            new ModelPreset("dashscope", "阿里云百炼", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "qwen-plus", "DASHSCOPE_API_KEY", new BigDecimal("0.30"), 131072,
                    List.of("qwen-plus", "qwen-max", "qwen-turbo", "qwen-long")),
            new ModelPreset("vllm", "vLLM 私有部署", "http://127.0.0.1:8001/v1", "Qwen2.5-7B-Instruct",
                    "VLLM_API_KEY", new BigDecimal("0.30"), 32768,
                    List.of("Qwen2.5-7B-Instruct", "Qwen2.5-14B-Instruct", "Qwen2.5-32B-Instruct")),
            new ModelPreset("ollama", "Ollama 本地", "http://127.0.0.1:11434/v1", "qwen2.5:7b",
                    "OLLAMA_API_KEY", new BigDecimal("0.30"), 32768,
                    List.of("qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b")),
            // 2026-11-04：「回声（演示兜底）」已按运营要求下线，不再作为可新增的模型类型。
            // agent 侧仍保留 echo 作为**进程内最后兜底**（模型缺 Key / 全部不可用时不至于整条会话失败），
            // 但它不再出现在管理端列表、用户端平台模型下拉与新增类型预设里。
            new ModelPreset("custom", "自定义（OpenAI 兼容）", "", "", "", new BigDecimal("0.30"), 0,
                    List.of()));

    /** 快照保留条数：够回溯最近若干次改动，又不会把表撑大。 */
    private static final int SNAPSHOT_KEEP = 30;

    private final ModelConfigMapper mapper;
    private final ModelConfigSnapshotMapper snapshotMapper;
    private final ObjectMapper objectMapper;
    private final ModelKeyCodec keyCodec;
    /** 服务间令牌：agent 的 `/internal/v1/*` 已强制校验（2026-10-18），无票直接 401。 */
    private final cn.aios.security.ServiceTokenProvider serviceTokenProvider;
    private final HttpClient httpClient = AgentHttpClient.agentBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    @Value("${aios.agent.base-url:http://127.0.0.1:8000}")
    private String agentBaseUrl;

    public ModelConfigService(ModelConfigMapper mapper, ModelConfigSnapshotMapper snapshotMapper,
                              ObjectMapper objectMapper, ModelKeyCodec keyCodec,
                              cn.aios.security.ServiceTokenProvider serviceTokenProvider) {
        this.mapper = mapper;
        this.snapshotMapper = snapshotMapper;
        this.objectMapper = objectMapper;
        this.keyCodec = keyCodec;
        this.serviceTokenProvider = serviceTokenProvider;
    }

    /** 调 agent 内部端点的统一鉴权头（单一口径，不要在各处手写）。 */
    private String serviceAuthHeader() {
        return "Bearer " + serviceTokenProvider.generate(cn.aios.security.ServiceTokenProvider.SVC_SERVER);
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
        return toView(cfg, SYNCED_STATE);
    }

    private ModelConfigView toView(ModelConfig cfg, String syncState) {
        return toView(cfg, agentConfiguredKeys(), syncState);
    }

    private ModelConfigView toView(ModelConfig cfg, Set<String> agentConfigured, String syncState) {
        String plain = keyCodec.decrypt(cfg.getApiKey());
        if (plain != null && !plain.isBlank()) {
            return ModelConfigView.of(cfg, plain, ModelConfigView.SOURCE_DB, syncState);
        }
        String envKey = readEnvKey(cfg.getApiKeyEnv());
        if (!envKey.isBlank()) {
            return ModelConfigView.of(cfg, envKey, ModelConfigView.SOURCE_ENV, syncState);
        }
        if (agentConfigured.contains(cfg.getProviderKey())) {
            return ModelConfigView.of(cfg, null, ModelConfigView.SOURCE_ENV, syncState);
        }
        return ModelConfigView.of(cfg, null, ModelConfigView.SOURCE_NONE, syncState);
    }

    private static final String SYNCED_STATE = ModelConfigView.SYNCED;

    /**
     * 密钥来源判定以**运行时**为准：管理端填写 > 本进程环境变量 > agent 侧已加载的同名环境变量。
     * 最后一条很关键 —— 服务端容器常常没有供应商 Key，但 agent 有，此时显示「未配置」是错的。
     */
    private ModelConfigView toView(ModelConfig cfg, Set<String> agentConfigured) {
        return toView(cfg, agentConfigured, SYNCED_STATE);
    }

    /** 问 agent 哪些 provider 已经拿到 Key（密钥只回「是否配置」，不回值）。 */
    private Set<String> agentConfiguredKeys() {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentBaseUrl + "/internal/v1/models"))
                    .header("Authorization", serviceAuthHeader())
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
        // 未填的参数补默认值：库里不留 NULL，两端读到的结构才一致
        applyParamDefaults(cfg, existing);

        // 写库前先快照：这是「一键回滚到上一版」的数据来源，也是审计痕迹
        snapshot("SAVE", operatorId);

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
        boolean synced = push();
        return toView(cfg, synced ? ModelConfigView.SYNCED : ModelConfigView.PENDING);
    }

    /**
     * 参数默认值（两端同口径，见 docs/72 §2）：
     * 温度 0.30 / 上下文 0 / 输出上限 0（不下发）/ 惩罚 0 / 超时 120s / 重试 3 / 流式开。
     *
     * <p>为什么在服务端补而不是只靠 SQL 默认值：前端提交的是整个对象，
     * 显式传 null 会盖掉列默认值；且编辑老行时希望「没填就是默认」而非「保留旧值」，
     * 因为表单里这些输入框始终有值。</p>
     */
    private void applyParamDefaults(ModelConfig cfg, ModelConfig existing) {
        if (cfg.getTemperature() == null) {
            cfg.setTemperature(existing != null && existing.getTemperature() != null
                    ? existing.getTemperature() : new BigDecimal("0.30"));
        }
        if (cfg.getMaxContext() == null) {
            cfg.setMaxContext(existing != null && existing.getMaxContext() != null ? existing.getMaxContext() : 0);
        }
        if (cfg.getMaxTokens() == null) {
            cfg.setMaxTokens(0);
        }
        if (cfg.getPresencePenalty() == null) {
            cfg.setPresencePenalty(BigDecimal.ZERO);
        }
        if (cfg.getFrequencyPenalty() == null) {
            cfg.setFrequencyPenalty(BigDecimal.ZERO);
        }
        if (cfg.getTimeoutSeconds() == null) {
            cfg.setTimeoutSeconds(120);
        }
        if (cfg.getRetryAttempts() == null) {
            cfg.setRetryAttempts(3);
        }
        if (cfg.getStreamEnabled() == null) {
            cfg.setStreamEnabled(true);
        }
        if (cfg.getTopP() != null && cfg.getTopP().compareTo(BigDecimal.ZERO) == 0) {
            // 0 与「不填」同义：不下发 top_p，避免网关把 top_p=0 当非法参数
            cfg.setTopP(null);
        }
    }

    /**
     * 掩码判定：列表只返回掩码，管理员打开编辑再保存时如果没动密钥，回传的就是掩码，
     * 此时必须保持库里的密文不变，否则会把真实密钥覆盖成 "****"。
     */
    private static boolean isMaskedValue(String v) {
        return v != null && v.contains("****");
    }

    public void delete(String providerKey) {
        snapshot("DELETE", null);
        mapper.delete(new LambdaQueryWrapper<ModelConfig>().eq(ModelConfig::getProviderKey, providerKey));
        push();
    }

    public void setDefault(String providerKey) {
        ModelConfig target = mapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getProviderKey, providerKey));
        if (target == null) {
            throw BizException.notFound("模型不存在：" + providerKey);
        }
        snapshot("DEFAULT", null);
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
        snapshot("STATUS", null);
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
                    .header("Authorization", serviceAuthHeader())
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

    /**
     * 把当前配置全量推给 agent 热加载。
     *
     * <p>返回「是否真的同步成功」：以前失败只打 WARN，前端看到保存成功却不知道
     * agent 还在用旧配置（docs/72 §4 一致性）。现在保存在库 + 推送两条腿分开记账，
     * 未同步成功的记录在列表里显示 PENDING，可再次保存或调 /sync 补推。
     */
    public boolean push() {
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
                o.put("topP", m.getTopP() == null ? null : m.getTopP().doubleValue());
                o.put("maxTokens", m.getMaxTokens() == null ? 0 : m.getMaxTokens());
                o.put("presencePenalty", m.getPresencePenalty() == null ? 0 : m.getPresencePenalty().doubleValue());
                o.put("frequencyPenalty", m.getFrequencyPenalty() == null ? 0 : m.getFrequencyPenalty().doubleValue());
                o.put("timeoutSeconds", m.getTimeoutSeconds() == null ? 120 : m.getTimeoutSeconds());
                o.put("retryAttempts", m.getRetryAttempts() == null ? 3 : m.getRetryAttempts());
                o.put("streamEnabled", m.getStreamEnabled() == null || m.getStreamEnabled());
                o.put("enabled", Boolean.TRUE.equals(m.getEnabled()));
                o.put("isDefault", Boolean.TRUE.equals(m.getIsDefault()));
                return o;
            }).toList();
            String body = objectMapper.writeValueAsString(Map.of("models", models, "default", defaultKey()));
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentBaseUrl + "/internal/v1/models/apply"))
                    .header("Authorization", serviceAuthHeader())
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(5))
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            boolean ok = resp.statusCode() == 200;
            if (ok) {
                // agent 会逐条校验：被拒的条目意味着「它仍在用旧值」，不能报成同步成功
                JsonNode rejected = objectMapper.readTree(resp.body()).path("rejected");
                if (rejected.isArray() && !rejected.isEmpty()) {
                    log.warn("agent 拒绝了 {} 条模型配置：{}", rejected.size(), rejected);
                    return false;
                }
            }
            log.info("model config pushed to agent: {} entries, agent status={}", models.size(), resp.statusCode());
            return ok;
        } catch (Exception e) {
            log.warn("push model config to agent failed (agent offline?): {}", e.getMessage());
            return false;
        }
    }

    // ---------- 快照 / 历史 / 回滚 ----------

    /** 写一份当前全量快照（写操作前调用）。快照失败不影响主流程，但会留下告警。 */
    private void snapshot(String reason, Long operatorId) {
        try {
            List<ModelConfig> all = mapper.selectList(null);
            ModelConfigSnapshot snap = new ModelConfigSnapshot();
            snap.setReason(reason);
            snap.setTotal(all.size());
            snap.setSnapshotJson(objectMapper.writeValueAsString(all));
            snap.setOperatorId(operatorId);
            snap.setCreatedAt(LocalDateTime.now());
            snapshotMapper.insert(snap);
            pruneSnapshots();
        } catch (Exception e) {
            log.warn("模型配置快照写入失败（不影响保存）：{}", e.getMessage());
        }
    }

    private void pruneSnapshots() {
        Long total = snapshotMapper.selectCount(null);
        if (total == null || total <= SNAPSHOT_KEEP) {
            return;
        }
        List<ModelConfigSnapshot> old = snapshotMapper.selectList(
                new LambdaQueryWrapper<ModelConfigSnapshot>()
                        .orderByAsc(ModelConfigSnapshot::getId)
                        .last("limit " + (int) (total - SNAPSHOT_KEEP)));
        for (ModelConfigSnapshot s : old) {
            snapshotMapper.deleteById(s.getId());
        }
    }

    /** 配置历史（列表只回元信息，不回快照正文）。 */
    public List<Map<String, Object>> history() {
        return snapshotMapper.selectList(new LambdaQueryWrapper<ModelConfigSnapshot>()
                        .orderByDesc(ModelConfigSnapshot::getId)
                        .last("limit 20"))
                .stream().map(s -> {
                    Map<String, Object> o = new LinkedHashMap<>();
                    o.put("id", s.getId());
                    o.put("reason", s.getReason());
                    o.put("total", s.getTotal());
                    o.put("operatorId", s.getOperatorId());
                    o.put("createdAt", s.getCreatedAt());
                    return o;
                }).toList();
    }

    /**
     * 回滚到指定快照：先给「当前状态」也留一份快照（回滚本身可撤销），
     * 再用快照内容整体替换 model_config 并推送热更新。
     *
     * <p>事务内完成：任一步失败整体回滚，库里不会停在半新半旧的状态；
     * 推送失败不回滚数据库（配置已是运营要的那份），返回 synced=false 让前端提示补推。
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> rollback(Long snapshotId, Long operatorId) {
        ModelConfigSnapshot snap = snapshotMapper.selectById(snapshotId);
        if (snap == null) {
            throw BizException.notFound("快照不存在：" + snapshotId);
        }
        List<ModelConfig> rows;
        try {
            rows = objectMapper.readValue(snap.getSnapshotJson(),
                    new com.fasterxml.jackson.core.type.TypeReference<List<ModelConfig>>() { });
        } catch (Exception e) {
            throw BizException.badRequest("快照内容无法解析：" + e.getMessage());
        }
        snapshot("ROLLBACK", operatorId);
        mapper.delete(new LambdaQueryWrapper<ModelConfig>());
        for (ModelConfig row : rows) {
            row.setId(null);   // 重新分配主键，避免与当前行 id 冲突
            mapper.insert(row);
        }
        boolean synced = push();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("snapshotId", snapshotId);
        out.put("restored", rows.size());
        out.put("synced", synced);
        out.put("total", list().size());
        log.info("model config rolled back to snapshot {} ({} rows, synced={})", snapshotId, rows.size(), synced);
        return out;
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

    /**
     * 新增模型的类型预设：选中后自动带出接入地址/模型名/密钥环境变量名。
     *
     * <p>{@code models} 是该供应商的常用模型名候选（2026-11-04）：厂家发布新模型时，
     * 运营只需在下拉里换成新名字即可调用，不用改代码、不用重启。
     */
    public record ModelPreset(String type, String label, String baseUrl, String defaultModel,
                              String apiKeyEnv, BigDecimal temperature, Integer maxContext,
                              List<String> models) {
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
