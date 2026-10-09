package cn.aioa.project.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.service.PmExpenseService;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 项目经费流水接口（PM 批次 4，V73）。设计依据 {@code docs/40 §6.3} + {@code docs/43 §4}。
 *
 * <p><b>刻意没有 PUT / DELETE</b>：用户关键词「经费…不能修改」⇒ 账目 append-only，
 * 写错只能 {@code POST .../reverse}（红冲）。这是本控制器唯一「写」的两种形态：
 * 追加、红冲。任何后来者想加 update/delete 端点，先读 {@link PmExpenseService} 的类注释。</p>
 *
 * <p>权限一律在 {@link PmExpenseService} 内判定（{@code requireVisible} + {@code requireWrite}），
 * 控制器不做二次鉴权（两处判定迟早漂移）。</p>
 */
@RestController
@RequestMapping("/api/v1/pm")
@RequiredArgsConstructor
public class PmExpenseController {

    private final OrgGuard guard;
    private final PmExpenseService expenseService;

    /** 经费流水：明细 + 预算执行汇总。筛选 {@code direction|category} 只影响明细，汇总按全量算。 */
    @GetMapping("/projects/{id}/expenses")
    public ApiResponse<Map<String, Object>> list(@PathVariable Long id,
                                                 @RequestParam(required = false) String direction,
                                                 @RequestParam(required = false) String category) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(expenseService.list(u, id, direction, category));
    }

    /** 追加一条流水（成本记录 / 人员费用 / 费用明细…）。 */
    @PostMapping("/projects/{id}/expenses")
    public ApiResponse<Map<String, Object>> create(@PathVariable Long id,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(expenseService.create(u, id, body));
    }

    /**
     * 红冲一条流水（原行不改，追加反向行）。
     *
     * <p>负向约束（可断言）：红冲行不能再被红冲；同一原行不能重复红冲（重复调用 → 409）。</p>
     */
    @PostMapping("/projects/{id}/expenses/{expenseId}/reverse")
    public ApiResponse<Map<String, Object>> reverse(@PathVariable Long id,
                                                    @PathVariable Long expenseId,
                                                    @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        String reason = body == null ? null : String.valueOf(body.getOrDefault("reason", ""));
        return ApiResponse.ok(expenseService.reverse(u, id, expenseId, reason));
    }
}
