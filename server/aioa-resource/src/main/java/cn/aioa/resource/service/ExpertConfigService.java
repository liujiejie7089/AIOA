package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.ExpertConfig;
import cn.aioa.resource.mapper.ExpertConfigMapper;
import cn.aioa.resource.model.ExpertSettings;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 专家配置解析：把「全局默认 / 租户 / 机构 / 部门 / 个人」五层片段 merge 成一份最终配置。
 *
 * <p>设计要点（对应方案 P1 / B3 / B4 / B6）：</p>
 * <ul>
 *   <li>优先级 {@code GLOBAL < TENANT < INSTITUTION < DEPT < USER}，同层内
 *       {@code expert_key='*'}（全局默认片段）低于具体的 expert_key；</li>
 *   <li>解析结果带 {@code sources}（每个配置项最终来自哪一层），让「配置为什么是这个值」可解释；</li>
 *   <li>所有配置真实作用于运行逻辑：解析结果会随 run 请求下发给 agent，
 *       由 agent 回传 {@code effective_params}，形成「配置 → 生效 → 可验证」闭环。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ExpertConfigService {

    private final ExpertConfigMapper configMapper;
    private final ObjectMapper objectMapper;

    /** 五层顺序（低 → 高）。 */
    private static final List<String> LAYER_ORDER = List.of(
            ExpertConfig.GLOBAL, ExpertConfig.TENANT, ExpertConfig.INSTITUTION,
            ExpertConfig.DEPT, ExpertConfig.USER);

    /** 各层对应的作用域 ID（与 LAYER_ORDER 一一对应）。 */
    private static List<Long> scopeIdsOf(Long tenantId, Long institutionId, Long deptId, Long userId) {
        return List.of(0L, tenantId == null ? 0L : tenantId,
                institutionId == null ? 0L : institutionId,
                deptId == null ? 0L : deptId,
                userId == null ? 0L : userId);
    }

    /** 系统默认值：任何层都没配时的兜底，保证专家「开箱可用」。 */
    public ExpertSettings defaults() {
        ExpertSettings s = new ExpertSettings();
        s.setEnabled(true);
        s.setVisibleScope("ALL");
        s.setDefaultEnabled(false);
        s.setKbScope("ALL");
        s.setModel("mock-default");
        s.setTemperature(0.3);
        s.setTopK(5);
        s.setThreshold(0.35);
        s.setRetrievalMode(ExpertSettings.MODE_HYBRID);
        s.setSort(100);
        s.setChunkSize(500);
        s.setChunkOverlap(50);
        Map<String, Boolean> tools = new LinkedHashMap<>();
        tools.put("sql_query", true);
        tools.put("python_script", true);
        tools.put("kb_search", true);
        s.setTools(tools);
        return s;
    }

    /**
     * 解析某个专家在某个用户上下文下的最终配置。
     *
     * @return ResolvedConfig（最终配置 + 每个键的来源层级 + 命中的层）
     */
    public ResolvedConfig resolve(Long tenantId, Long institutionId, Long deptId, Long userId, String expertKey) {
        if (expertKey == null || expertKey.isBlank()) {
            throw BizException.badRequest("expertKey 不能为空");
        }
        List<Long> scopeIds = scopeIdsOf(tenantId, institutionId, deptId, userId);
        long tid = tenantId == null ? 0L : tenantId;

        // 一次取回「全局 + 本租户」下与该专家相关的所有片段，内存里按层过滤
        // V36 需求⑤：待审（PENDING）/ 已驳回（REJECTED）的片段**不参与解析**，
        // 自然回落上一层（继承语义），否则「审核」形同虚设。
        List<ExpertConfig> rows = configMapper.selectList(new LambdaQueryWrapper<ExpertConfig>()
                .in(ExpertConfig::getTenantId, List.of(0L, tid))
                .in(ExpertConfig::getExpertKey, List.of(ExpertConfig.WILDCARD, expertKey))
                .isNull(ExpertConfig::getDeletedAt)
                .and(w -> w.eq(ExpertConfig::getAuditStatus, ExpertConfig.AUDIT_APPROVED)
                        .or().isNull(ExpertConfig::getAuditStatus)));

        ExpertSettings merged = defaults();
        Map<String, String> sources = new LinkedHashMap<>();
        List<LayerHit> hits = new ArrayList<>();

        for (int i = 0; i < LAYER_ORDER.size(); i++) {
            String layer = LAYER_ORDER.get(i);
            long scopeId = scopeIds.get(i);
            // 同层：先通配符片段，再具体专家片段（后者优先级更高）
            for (String keyWanted : List.of(ExpertConfig.WILDCARD, expertKey)) {
                for (ExpertConfig row : rows) {
                    if (!layer.equals(row.getScopeType()) || !keyWanted.equals(row.getExpertKey())) {
                        continue;
                    }
                    if (!scopeIdEquals(layer, row.getScopeId(), scopeId)) {
                        continue;
                    }
                    Map<String, Object> partial = readJson(row.getConfigJson());
                    int n = merged.mergeFrom(partial, layerLabel(layer, row.getExpertKey(), scopeId), sources);
                    if (n > 0) {
                        hits.add(new LayerHit(layer, row.getExpertKey(), scopeId, partial));
                    }
                }
            }
        }
        return new ResolvedConfig(expertKey, merged, sources, hits);
    }

    /** 作用域比对：TENANT 层 scope_id 允许为 0 或租户ID（历史数据兼容）；其余层必须相等。 */
    private static boolean scopeIdEquals(String layer, Long rowScopeId, long want) {
        long got = rowScopeId == null ? 0L : rowScopeId;
        if (ExpertConfig.TENANT.equals(layer)) {
            return got == 0L || got == want;
        }
        return got == want;
    }

    private static String layerLabel(String layer, String expertKey, long scopeId) {
        return ExpertConfig.WILDCARD.equals(expertKey) ? layer + ":*" : layer + "#" + scopeId;
    }

    private Map<String, Object> readJson(String json) {
        if (json == null || json.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {
            });
        } catch (Exception e) {
            log.warn("expert_config 解析失败，忽略该片段: {}", e.getMessage());
            return Map.of();
        }
    }

    /**
     * 写入/更新一条配置片段（幂等 upsert）。
     *
     * <p>审核态（V36 需求⑤）由调用方给出 {@code auditStatus}：</p>
     * <ul>
     *   <li>{@code APPROVED} —— 平台管理员写入，或 {@code USER} 层（只影响本人）写入，直接生效；</li>
     *   <li>{@code PENDING} —— 租户 / 企业管理员写团队层，需平台管理员放行；
     *       若同键已有待审行则**就地更新**，不新建第二行（避免唯一键冲突与草稿堆叠），
     *       且清空上一轮审核意见，避免「用旧驳回理由看待新内容」；</li>
     *   <li>{@code null} —— 保持原有审核态（历史调用方兼容；新行为 {@code APPROVED}）。</li>
     * </ul>
     */
    public ExpertConfig save(Long tenantId, String scopeType, Long scopeId, String expertKey,
                             Map<String, Object> patch, boolean merge, Long operatorId) {
        return save(tenantId, scopeType, scopeId, expertKey, patch, merge, operatorId, null);
    }

    public ExpertConfig save(Long tenantId, String scopeType, Long scopeId, String expertKey,
                             Map<String, Object> patch, boolean merge, Long operatorId, String auditStatus) {
        if (scopeType == null || !LAYER_ORDER.contains(scopeType)) {
            throw BizException.badRequest("scopeType 必须是 GLOBAL/TENANT/INSTITUTION/DEPT/USER");
        }
        if (expertKey == null || expertKey.isBlank()) {
            throw BizException.badRequest("expertKey 不能为空");
        }
        long tid = ExpertConfig.GLOBAL.equals(scopeType) ? 0L : (tenantId == null ? 0L : tenantId);
        long sid = scopeId == null ? 0L : scopeId;

        ExpertConfig row = configMapper.selectOne(new LambdaQueryWrapper<ExpertConfig>()
                .eq(ExpertConfig::getTenantId, tid)
                .eq(ExpertConfig::getScopeType, scopeType)
                .eq(ExpertConfig::getScopeId, sid)
                .eq(ExpertConfig::getExpertKey, expertKey)
                .isNull(ExpertConfig::getDeletedAt)
                .last("LIMIT 1"));

        // 物理清理同键的软删残留，避免唯一键冲突（实体不再 @TableLogic 自动过滤）
        configMapper.delete(new LambdaQueryWrapper<ExpertConfig>()
                .eq(ExpertConfig::getTenantId, tid)
                .eq(ExpertConfig::getScopeType, scopeType)
                .eq(ExpertConfig::getScopeId, sid)
                .eq(ExpertConfig::getExpertKey, expertKey)
                .isNotNull(ExpertConfig::getDeletedAt));

        Map<String, Object> next = new LinkedHashMap<>();
        if (merge && row != null && row.getConfigJson() != null) {
            next.putAll(readJson(row.getConfigJson()));
        }
        next.putAll(patch == null ? Map.of() : patch);

        if (row == null) {
            row = new ExpertConfig();
            row.setTenantId(tid);
            row.setScopeType(scopeType);
            row.setScopeId(sid);
            row.setExpertKey(expertKey);
            row.setCreatedBy(operatorId);
        }
        try {
            row.setConfigJson(objectMapper.writeValueAsString(next));
        } catch (Exception e) {
            throw BizException.badRequest("配置序列化失败");
        }
        if (auditStatus != null) {
            row.setAuditStatus(auditStatus);
            if (ExpertConfig.AUDIT_PENDING.equalsIgnoreCase(auditStatus)) {
                // 内容已变 → 旧审核结论失效，避免用上一轮的意见看待新内容
                row.setAuditNote(null);
                row.setReviewedBy(null);
                row.setReviewedAt(null);
            }
        } else if (row.getAuditStatus() == null || row.getAuditStatus().isBlank()) {
            row.setAuditStatus(ExpertConfig.AUDIT_APPROVED);
        }
        if (row.getId() == null) {
            configMapper.insert(row);
        } else {
            configMapper.updateById(row);
        }
        log.info("expert_config saved: tenant={} {}/{} expert={} keys={} audit={}",
                tid, scopeType, sid, expertKey, next.keySet(), row.getAuditStatus());
        return row;
    }

    /** 删除一条配置片段（物理删除，配置量小、语义简单，避免软删带来的唯一键冲突）。 */
    public void delete(Long tenantId, String scopeType, Long scopeId, String expertKey) {
        configMapper.delete(new LambdaQueryWrapper<ExpertConfig>()
                .eq(ExpertConfig::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(ExpertConfig::getScopeType, scopeType)
                .eq(ExpertConfig::getScopeId, scopeId == null ? 0L : scopeId)
                .eq(ExpertConfig::getExpertKey, expertKey));
    }

    /**
     * 删除某租户下某 experts 的**全部**配置片段（删除专家时级联）。
     *
     * <p>为什么必须级联：片段是按 {@code expert_key} 挂的，专家行被删后这些片段就成了
     * 「没有主人的孤儿」。若同一 key 日后被重新创建，旧片段会**静默复活**
     * （例如上一轮设过的 {@code enabled=false} / 旧 systemPrompt 直接生效），
     * 表现为「新建的专家一上来就是关的 / 提示词是别人留下的」。物理删除，语义明确。</p>
     *
     * <p>只删 {@code tenantId} 名下的片段：平台模板（tenant 0）与租户副本（tenant N）
     * 各管各的，删租户副本不该动全局模板的片段。</p>
     *
     * @return 实际删除的片段条数
     */
    public int deleteAll(Long tenantId, String expertKey) {
        if (expertKey == null || expertKey.isBlank()) {
            throw BizException.badRequest("expertKey 不能为空");
        }
        int n = configMapper.delete(new LambdaQueryWrapper<ExpertConfig>()
                .eq(ExpertConfig::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(ExpertConfig::getExpertKey, expertKey));
        log.info("expert_config purged: tenant={} expert={} rows={}", tenantId, expertKey, n);
        return n;
    }

    /**
     * 删除某 key 下、**除了 {@code keepTenantIds} 之外**的全部配置片段。
     *
     * <p><b>为什么还需要一个「跨租户」的清理</b>：{@link #deleteAll(Long, String)} 只清调用者
     * 自己名下（{@code tenantId}）的片段。但租户可以在**没有导入副本**的情况下写过片段 ——
     * 最典型的就是「某租户把这位专家停用了」（{@code expert_config(tenant_id=2, expert_key=x,
     * enabled=false)}）。此时平台管理员删除全局模板，这条片段就没主人了。</p>
     *
     * <p>危害不是「多一行垃圾」，而是<b>同一 key 日后被重建时旧片段静默复活</b>：
     * 新专家在租户 2 那里一上来就是「关」的（或提示词是上一轮留下的）。
     * 2026-09-24 实测：删除专家后 {@code SELECT * FROM expert_config WHERE expert_key=?}
     * 仍剩 1 条 {@code {"enabled": true}}（tenant_id=2、PENDING），即为此类孤儿。</p>
     *
     * <p><b>判据（谁该保留）</b>：只有「该租户名下还有存活的 {@code ai_expert} 行」才保留；
     * 全局模板仍在时，各租户对它的覆盖片段依然有意义，因此<b>调用方不应传 keepTenantIds 为空</b>去清跨租户片段 ——
     * 这个前提由调用方（删除专家端点）判定，本方法只负责执行。</p>
     *
     * @param keepTenantIds 仍需保留片段的租户；传<b>空集合</b>表示「这个 key 已彻底不存在，全清」
     * @return 物理删除的片段条数
     */
    public int deleteAllExceptTenants(String expertKey, Collection<Long> keepTenantIds) {
        if (expertKey == null || expertKey.isBlank()) {
            throw BizException.badRequest("expertKey 不能为空");
        }
        LambdaQueryWrapper<ExpertConfig> w = new LambdaQueryWrapper<ExpertConfig>()
                .eq(ExpertConfig::getExpertKey, expertKey);
        if (keepTenantIds != null && !keepTenantIds.isEmpty()) {
            w.notIn(ExpertConfig::getTenantId, keepTenantIds);
        }
        int n = configMapper.delete(w);
        log.info("expert_config purged(orphan): expert={} keepTenants={} rows={}", expertKey, keepTenantIds, n);
        return n;
    }

    /**
     * 「专家在某用户上下文下是否启用」的<b>唯一判据</b>。
     *
     * <p>口径 = <b>配置层</b> {@code enabled}（五层 merge 之后的结果），而<b>不是</b>
     * {@code ai_expert.enabled} 列。管理端「启用 / 停用」开关写的就是配置层，
     * 所以用户端目录必须走这里。</p>
     *
     * <p>为什么单独抽出来：2026-09-24 实测缺陷 —— 管理端停用只写了
     * {@code expert_config}，而用户端 {@code CatalogService} 只按 {@code ai_expert.enabled}
     * 列过滤（该列**从来没有任何代码写过 false**，两处写入都硬编码 true），
     * 于是出现「管理员明确停用了，用户端照旧能选能用」。
     * 这正是铁律 #1 禁止的「同一决策点两处判定」：本方法把它收敛回一处。</p>
     */
    public boolean isEnabled(Long tenantId, Long institutionId, Long deptId, Long userId, String expertKey) {
        return Boolean.TRUE.equals(
                resolve(tenantId, institutionId, deptId, userId, expertKey).settings().getEnabled());
    }

    /** 列出某专家在某租户下的所有配置片段（管理端展示覆盖链路）。 */
    public List<ExpertConfig> list(Long tenantId, String expertKey) {
        LambdaQueryWrapper<ExpertConfig> w = new LambdaQueryWrapper<ExpertConfig>()
                .eq(ExpertConfig::getTenantId, tenantId == null ? 0L : tenantId)
                .isNull(ExpertConfig::getDeletedAt);
        if (expertKey != null && !expertKey.isBlank()) {
            w.eq(ExpertConfig::getExpertKey, expertKey);
        }
        return configMapper.selectList(w);
    }

    /** 解析结果：最终配置 + 可解释来源。 */
    public record ResolvedConfig(
            String expertKey,
            ExpertSettings settings,
            /** 键 -> 最终生效来源层级（如 TENANT#2）。 */
            Map<String, String> sources,
            /** 命中的配置片段，按优先级从低到高。 */
            List<LayerHit> layers
    ) {
        /** 转成下发给 agent 的 Map（含来源，便于前端与自检核对）。 */
        public Map<String, Object> toPayload() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("expertKey", expertKey);
            m.put("enabled", settings.getEnabled());
            m.put("visibleScope", settings.getVisibleScope());
            m.put("defaultEnabled", settings.getDefaultEnabled());
            m.put("kbScope", settings.getKbScope());
            m.put("model", settings.getModel());
            m.put("temperature", settings.getTemperature());
            m.put("topK", settings.getTopK());
            m.put("threshold", settings.getThreshold());
            m.put("retrievalMode", settings.getRetrievalMode());
            m.put("tools", settings.getTools());
            m.put("sort", settings.getSort());
            m.put("chunkSize", settings.getChunkSize());
            m.put("chunkOverlap", settings.getChunkOverlap());
            m.put("systemPrompt", settings.getSystemPrompt());
            m.put("knowledgeScope", settings.getKnowledgeScope());
            m.put("sources", sources);
            return m;
        }
    }

    /** 命中的一层配置。 */
    public record LayerHit(String scopeType, String expertKey, Long scopeId, Map<String, Object> config) {
    }
}
