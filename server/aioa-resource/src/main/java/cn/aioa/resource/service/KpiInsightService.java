package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.http.AgentHttpClient;
import cn.aioa.resource.entity.BizKpi;
import cn.aioa.resource.entity.BizKpiInsight;
import cn.aioa.resource.entity.BizKpiTrend;
import cn.aioa.resource.mapper.BizKpiInsightMapper;
import cn.aioa.resource.mapper.BizKpiMapper;
import cn.aioa.resource.mapper.BizKpiTrendMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 经营数据「AI 解读」——真实调用模型生成，绝不写死文案（V33 功能项六）。
 *
 * <p>之前的实现是看板直接读 {@code biz_kpi_insight.content}，内容只能靠管理端手工录入，
 * 「AI 解读」名不副实。现在提供按需生成：把当前期间的指标与趋势作为**唯一依据**交给模型，
 * 要求它只做解读不编数字，生成结果落库复用（同一租户同一期间一行）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KpiInsightService {

    /** 输出约束：中文纯文本、结论先行、给可执行建议、不编造数据、无 markdown 标记。 */
    private static final String SYSTEM_PROMPT = """
            你是 AIOA 智能办公平台的经营数据分析师。你只依据用户给出的指标与趋势做解读，
            严禁编造、推测任何未给出的数字；数据为空或不足以支撑结论时，直接说明数据不足。
            输出要求：中文纯文本，140–220 字；先给一句总体结论，再给 2 条可执行的经营建议；
            不要使用 markdown 标记（不要 #、*、- 开头），不要分点符号，用自然段表达。
            """;

    private static final int MAX_TOKENS = 600;
    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("MM-dd HH:mm");

    private final BizKpiMapper kpiMapper;
    private final BizKpiTrendMapper trendMapper;
    private final BizKpiInsightMapper insightMapper;
    private final ObjectMapper objectMapper;

    @Value("${aioa.agent.base-url:http://localhost:8000}")
    private String agentBaseUrl;

    private final HttpClient http = AgentHttpClient.agentBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    /**
     * 生成并保存经营解读。
     *
     * @param tenantId 租户
     * @param period   month / quarter
     * @return {insight, source, model, generatedAt, promptTokens}
     */
    public Map<String, Object> generate(Long tenantId, String period) {
        Long tid = tenantId == null ? 0L : tenantId;
        String p = normalizePeriod(period);

        List<BizKpi> metrics = kpiMapper.selectList(new LambdaQueryWrapper<BizKpi>()
                .eq(BizKpi::getTenantId, tid)
                .eq(BizKpi::getPeriod, p)
                .orderByAsc(BizKpi::getSortNo)
                .orderByAsc(BizKpi::getId));
        if (metrics.isEmpty()) {
            throw BizException.badRequest("该期间暂无可解读的经营数据，请管理员先在管理端「经营数据」录入指标");
        }
        List<BizKpiTrend> trend = trendMapper.selectList(new LambdaQueryWrapper<BizKpiTrend>()
                .eq(BizKpiTrend::getTenantId, tid)
                .eq(BizKpiTrend::getPeriod, p)
                .orderByAsc(BizKpiTrend::getSortNo)
                .orderByAsc(BizKpiTrend::getId));

        String prompt = buildPrompt(p, metrics, trend);
        ModelResult result = callModel(prompt);

        String content = result.content == null ? "" : result.content.trim();
        if (content.isBlank()) {
            throw BizException.badRequest("AI 未返回解读内容"
                    + (result.error == null ? "" : "：" + result.error));
        }

        String source = "AI 生成 · " + (result.model == null ? "默认模型" : result.model)
                + " · " + LocalDateTime.now().format(TS);
        save(tid, p, content, source);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("insight", content);
        out.put("source", source);
        out.put("model", result.model);
        out.put("period", p);
        out.put("generatedAt", LocalDateTime.now().toString());
        out.put("promptTokens", result.promptTokens);
        return out;
    }

    /** 把指标与趋势拼成「模型唯一可见的事实」。 */
    private static String buildPrompt(String period, List<BizKpi> metrics, List<BizKpiTrend> trend) {
        StringBuilder sb = new StringBuilder();
        sb.append("统计期间：").append("month".equals(period) ? "本月" : "本季").append('\n');
        sb.append("核心经营指标：\n");
        for (BizKpi k : metrics) {
            sb.append(" - ").append(k.getLabel()).append("：").append(nvl(k.getValueText()));
            if (k.getDeltaText() != null && !k.getDeltaText().isBlank()) {
                sb.append("（").append(Integer.valueOf(1).equals(k.getUp()) ? "较上期上升 " : "较上期下降 ")
                        .append(k.getDeltaText()).append("）");
            }
            if (k.getCompareLabel() != null && !k.getCompareLabel().isBlank()) {
                sb.append("，").append(k.getCompareLabel());
            }
            sb.append('\n');
        }
        if (!trend.isEmpty()) {
            // 趋势表未存单位，故不臆造量纲；只给标签与数值，由模型在解读中避免声称具体单位
            sb.append("近 ").append(trend.size()).append(" 期趋势（数值）：\n");
            for (BizKpiTrend t : trend) {
                sb.append(" - ").append(t.getPointLabel()).append("：")
                        .append(t.getNumValue() == null ? "—" : t.getNumValue().toPlainString())
                        .append(Integer.valueOf(1).equals(t.getHot()) ? "（高点）" : "").append('\n');
            }
        }
        sb.append("\n请基于以上数据给出经营解读。");
        return sb.toString();
    }

    /** 调 agent 非流式补全（与数字员工定时任务同一通路，真实走模型网关）。 */
    private ModelResult callModel(String prompt) {
        try {
            String body = objectMapper.writeValueAsString(Map.of(
                    "prompt", prompt,
                    "system", SYSTEM_PROMPT,
                    "max_tokens", MAX_TOKENS));
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(agentBaseUrl + "/internal/v1/complete"))
                    .timeout(Duration.ofSeconds(150))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() / 100 != 2) {
                throw BizException.badRequest("AI 服务返回 HTTP " + resp.statusCode());
            }
            JsonNode node = objectMapper.readTree(resp.body());
            String error = node.hasNonNull("error") ? node.get("error").asText() : null;
            if (error != null && !error.isBlank()) {
                throw BizException.badRequest("AI 生成失败：" + error);
            }
            return new ModelResult(
                    node.path("content").asText(null),
                    node.path("model").asText(null),
                    node.path("usage").path("prompt_tokens").asInt(0),
                    null);
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            log.error("经营数据 AI 解读调用失败", e);
            throw BizException.badRequest("AI 解读生成失败："
                    + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()));
        }
    }

    /** 同租户同期间仅保留一行，重复生成则覆盖（解读是「当前事实」的快照）。 */
    private void save(Long tenantId, String period, String content, String source) {
        BizKpiInsight exist = insightMapper.selectOne(new LambdaQueryWrapper<BizKpiInsight>()
                .eq(BizKpiInsight::getTenantId, tenantId)
                .eq(BizKpiInsight::getPeriod, period)
                .last("LIMIT 1"));
        if (exist == null) {
            BizKpiInsight row = new BizKpiInsight();
            row.setTenantId(tenantId);
            row.setPeriod(period);
            row.setContent(content);
            row.setSourceText(source);
            row.setUpdatedAt(LocalDateTime.now());
            insightMapper.insert(row);
        } else {
            exist.setContent(content);
            exist.setSourceText(source);
            exist.setUpdatedAt(LocalDateTime.now());
            insightMapper.updateById(exist);
        }
    }

    private static String normalizePeriod(String period) {
        return BizKpi.PERIOD_QUARTER.equals(period) ? BizKpi.PERIOD_QUARTER : BizKpi.PERIOD_MONTH;
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }

    private record ModelResult(String content, String model, int promptTokens, String error) {
    }
}
