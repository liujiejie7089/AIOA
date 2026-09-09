package cn.aioa.admin.service;

import cn.aioa.admin.entity.ModelConfig;
import cn.aioa.admin.mapper.ModelConfigMapper;
import cn.aioa.common.exception.BizException;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 模型配置服务：管理端 CRUD + 变更后向 agent 推送热加载（/internal/v1/models/apply）。
 * 推送失败不影响配置保存（agent 下线场景），agent 恢复后管理端再次保存即可同步。
 */
@Slf4j
@Service
public class ModelConfigService {

    private final ModelConfigMapper mapper;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .build();

    @Value("${aioa.agent.base-url:http://127.0.0.1:8000}")
    private String agentBaseUrl;

    public ModelConfigService(ModelConfigMapper mapper, ObjectMapper objectMapper) {
        this.mapper = mapper;
        this.objectMapper = objectMapper;
    }

    public List<ModelConfig> list() {
        return mapper.selectList(new LambdaQueryWrapper<ModelConfig>()
                .orderByDesc(ModelConfig::getIsDefault)
                .orderByAsc(ModelConfig::getSort));
    }

    public String defaultKey() {
        ModelConfig d = mapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getIsDefault, true)
                .last("limit 1"));
        return d == null ? ModelConfig.DEFAULT_KEY : d.getProviderKey();
    }

    public ModelConfig upsert(ModelConfig cfg, Long operatorId) {
        LocalDateTime now = LocalDateTime.now();
        ModelConfig existing = mapper.selectOne(new LambdaQueryWrapper<ModelConfig>()
                .eq(ModelConfig::getProviderKey, cfg.getProviderKey()));
        if (existing == null) {
            cfg.setCreatedAt(now);
            cfg.setCreatedBy(operatorId);
            mapper.insert(cfg);
        } else {
            cfg.setId(existing.getId());
            cfg.setUpdatedAt(now);
            mapper.updateById(cfg);
        }
        if (Boolean.TRUE.equals(cfg.getIsDefault())) {
            clearOthers(cfg.getProviderKey());
        }
        push();
        return cfg;
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

    private void clearOthers(String keepKey) {
        mapper.update(null, new LambdaUpdateWrapper<ModelConfig>()
                .ne(ModelConfig::getProviderKey, keepKey)
                .set(ModelConfig::getIsDefault, false));
    }

    /** 把当前配置全量推给 agent 热加载；失败仅告警。 */
    public void push() {
        try {
            List<ModelConfig> all = list();
            List<Map<String, Object>> models = all.stream().map(m -> {
                Map<String, Object> o = new LinkedHashMap<>();
                o.put("key", m.getProviderKey());
                o.put("baseUrl", m.getBaseUrl());
                o.put("model", m.getModelName());
                o.put("apiKeyEnv", m.getApiKeyEnv());
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
}
