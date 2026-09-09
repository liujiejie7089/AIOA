package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
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
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 经营数据看板 —— 管理端维护（V1.2 新增）：
 *   指标卡   GET/POST/PUT/DELETE /api/v1/admin/kpi/metrics[/{id}]
 *   趋势柱   GET/POST/PUT/DELETE /api/v1/admin/kpi/trend[/{id}]
 *   AI 解读  GET/PUT           /api/v1/admin/kpi/insight?period=
 * 权限：仅租户管理员（手动检查，避免 AccessDeniedException 被兜底为 500）。
 */
@RestController
@RequestMapping("/api/v1/admin/kpi")
@RequiredArgsConstructor
public class AdminKpiController {

    private final BizKpiMapper kpiMapper;
    private final BizKpiTrendMapper trendMapper;
    private final BizKpiInsightMapper insightMapper;

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("经营数据维护仅租户管理员可操作");
        }
        return user;
    }

    /* ---------------- 指标卡 ---------------- */

    @GetMapping("/metrics")
    public ApiResponse<List<BizKpi>> metrics(@RequestParam(name = "period", defaultValue = BizKpi.PERIOD_MONTH) String period) {
        AuthUser user = requireAdmin();
        return ApiResponse.ok(kpiMapper.selectList(new LambdaQueryWrapper<BizKpi>()
                .eq(BizKpi::getTenantId, user.getTenantId())
                .eq(BizKpi::getPeriod, period)
                .orderByAsc(BizKpi::getSortNo)
                .orderByAsc(BizKpi::getId)));
    }

    @PostMapping("/metrics")
    public ApiResponse<BizKpi> createMetric(@RequestBody BizKpi body) {
        AuthUser user = requireAdmin();
        body.setId(null);
        body.setTenantId(user.getTenantId());
        body.setCreatedBy(user.getUserId());
        body.setUpdatedAt(LocalDateTime.now());
        if (body.getUp() == null) body.setUp(1);
        if (body.getSortNo() == null) body.setSortNo(99);
        kpiMapper.insert(body);
        return ApiResponse.ok(body);
    }

    @PutMapping("/metrics/{id}")
    public ApiResponse<BizKpi> updateMetric(@PathVariable Long id, @RequestBody BizKpi body) {
        AuthUser user = requireAdmin();
        BizKpi cur = kpiMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("指标不存在：" + id);
        }
        body.setId(id);
        body.setTenantId(cur.getTenantId());
        body.setCreatedBy(cur.getCreatedBy());
        body.setUpdatedAt(LocalDateTime.now());
        kpiMapper.updateById(body);
        return ApiResponse.ok(body);
    }

    @DeleteMapping("/metrics/{id}")
    public ApiResponse<Boolean> deleteMetric(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        BizKpi cur = kpiMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("指标不存在：" + id);
        }
        return ApiResponse.ok(kpiMapper.deleteById(id) > 0);
    }

    /* ---------------- 趋势柱 ---------------- */

    @GetMapping("/trend")
    public ApiResponse<List<BizKpiTrend>> trend(@RequestParam(name = "period", defaultValue = BizKpi.PERIOD_MONTH) String period) {
        AuthUser user = requireAdmin();
        return ApiResponse.ok(trendMapper.selectList(new LambdaQueryWrapper<BizKpiTrend>()
                .eq(BizKpiTrend::getTenantId, user.getTenantId())
                .eq(BizKpiTrend::getPeriod, period)
                .orderByAsc(BizKpiTrend::getSortNo)
                .orderByAsc(BizKpiTrend::getId)));
    }

    @PostMapping("/trend")
    public ApiResponse<BizKpiTrend> createTrend(@RequestBody BizKpiTrend body) {
        AuthUser user = requireAdmin();
        body.setId(null);
        body.setTenantId(user.getTenantId());
        body.setUpdatedAt(LocalDateTime.now());
        if (body.getHot() == null) body.setHot(0);
        if (body.getSortNo() == null) body.setSortNo(99);
        trendMapper.insert(body);
        return ApiResponse.ok(body);
    }

    @PutMapping("/trend/{id}")
    public ApiResponse<BizKpiTrend> updateTrend(@PathVariable Long id, @RequestBody BizKpiTrend body) {
        AuthUser user = requireAdmin();
        BizKpiTrend cur = trendMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("趋势点不存在：" + id);
        }
        body.setId(id);
        body.setTenantId(cur.getTenantId());
        body.setUpdatedAt(LocalDateTime.now());
        trendMapper.updateById(body);
        return ApiResponse.ok(body);
    }

    @DeleteMapping("/trend/{id}")
    public ApiResponse<Boolean> deleteTrend(@PathVariable Long id) {
        AuthUser user = requireAdmin();
        BizKpiTrend cur = trendMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())) {
            throw BizException.notFound("趋势点不存在：" + id);
        }
        return ApiResponse.ok(trendMapper.deleteById(id) > 0);
    }

    /* ---------------- AI 解读（每租户每周期一条） ---------------- */

    @GetMapping("/insight")
    public ApiResponse<BizKpiInsight> insight(@RequestParam(name = "period", defaultValue = BizKpi.PERIOD_MONTH) String period) {
        AuthUser user = requireAdmin();
        BizKpiInsight ins = insightMapper.selectOne(new LambdaQueryWrapper<BizKpiInsight>()
                .eq(BizKpiInsight::getTenantId, user.getTenantId())
                .eq(BizKpiInsight::getPeriod, period)
                .last("LIMIT 1"));
        return ApiResponse.ok(ins == null ? new BizKpiInsight() : ins);
    }

    @PutMapping("/insight")
    public ApiResponse<BizKpiInsight> upsertInsight(@RequestParam(name = "period", defaultValue = BizKpi.PERIOD_MONTH) String period,
                                                    @RequestBody BizKpiInsight body) {
        AuthUser user = requireAdmin();
        BizKpiInsight cur = insightMapper.selectOne(new LambdaQueryWrapper<BizKpiInsight>()
                .eq(BizKpiInsight::getTenantId, user.getTenantId())
                .eq(BizKpiInsight::getPeriod, period)
                .last("LIMIT 1"));
        if (cur == null) {
            cur = new BizKpiInsight();
            cur.setTenantId(user.getTenantId());
            cur.setPeriod(period);
        }
        cur.setContent(body.getContent());
        cur.setSourceText(body.getSourceText());
        cur.setUpdatedAt(LocalDateTime.now());
        if (cur.getId() == null) insightMapper.insert(cur);
        else insightMapper.updateById(cur);
        return ApiResponse.ok(cur);
    }
}
