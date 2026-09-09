package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.BizKpi;
import cn.aioa.resource.entity.BizKpiInsight;
import cn.aioa.resource.entity.BizKpiTrend;
import cn.aioa.resource.mapper.BizKpiInsightMapper;
import cn.aioa.resource.mapper.BizKpiMapper;
import cn.aioa.resource.mapper.BizKpiTrendMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 经营数据看板（V1.2 新增，用户端只读）：
 *   GET /api/v1/kpi/board?period=month|quarter
 *     → {period, metrics[], trend[], insight, source}
 * 数据由管理端「经营数据」页维护（/api/v1/admin/kpi/**）。
 */
@RestController
@RequestMapping("/api/v1/kpi")
@RequiredArgsConstructor
public class KpiController {

    private final BizKpiMapper kpiMapper;
    private final BizKpiTrendMapper trendMapper;
    private final BizKpiInsightMapper insightMapper;

    public record MetricView(Long id, String label, String value, String delta, boolean up, String compare) {
    }

    public record TrendView(Long id, String label, double value, boolean hot) {
    }

    @GetMapping("/board")
    public ApiResponse<Map<String, Object>> board(
            @RequestParam(name = "period", defaultValue = BizKpi.PERIOD_MONTH) String period) {
        AuthUser user = AuthUserContext.require();
        Long tid = user.getTenantId();
        String p = normalizePeriod(period);

        List<MetricView> metrics = kpiMapper.selectList(new LambdaQueryWrapper<BizKpi>()
                        .eq(BizKpi::getTenantId, tid)
                        .eq(BizKpi::getPeriod, p)
                        .orderByAsc(BizKpi::getSortNo)
                        .orderByAsc(BizKpi::getId))
                .stream()
                .map(k -> new MetricView(k.getId(), k.getLabel(), k.getValueText(), k.getDeltaText(),
                        Integer.valueOf(1).equals(k.getUp()), k.getCompareLabel()))
                .toList();

        List<TrendView> trend = trendMapper.selectList(new LambdaQueryWrapper<BizKpiTrend>()
                        .eq(BizKpiTrend::getTenantId, tid)
                        .eq(BizKpiTrend::getPeriod, p)
                        .orderByAsc(BizKpiTrend::getSortNo)
                        .orderByAsc(BizKpiTrend::getId))
                .stream()
                .map(t -> new TrendView(t.getId(), t.getPointLabel(),
                        t.getNumValue() == null ? 0d : t.getNumValue().doubleValue(),
                        Integer.valueOf(1).equals(t.getHot())))
                .toList();

        BizKpiInsight ins = insightMapper.selectOne(new LambdaQueryWrapper<BizKpiInsight>()
                .eq(BizKpiInsight::getTenantId, tid)
                .eq(BizKpiInsight::getPeriod, p)
                .last("LIMIT 1"));

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("period", p);
        data.put("metrics", metrics);
        data.put("trend", trend);
        data.put("insight", ins == null ? "" : nvl(ins.getContent()));
        data.put("source", ins == null ? "" : nvl(ins.getSourceText()));
        return ApiResponse.ok(data);
    }

    private static String normalizePeriod(String period) {
        return BizKpi.PERIOD_QUARTER.equals(period) ? BizKpi.PERIOD_QUARTER : BizKpi.PERIOD_MONTH;
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }
}
