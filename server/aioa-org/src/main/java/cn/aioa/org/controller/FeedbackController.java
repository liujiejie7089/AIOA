package cn.aioa.org.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.service.FeedbackService;
import cn.aioa.security.AuthUserContext;
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
 * 投诉与建议（V63）—— 用户端「我的 → 投诉与建议」的服务端。
 *
 * <p>四个动作构成完整闭环：</p>
 * <table border="1">
 *   <tr><th>接口</th><th>谁用</th><th>作用</th></tr>
 *   <tr><td>{@code POST /api/v1/feedback}</td><td>任何机构成员</td>
 *       <td>提交。响应里带 {@code delivered} / {@code assigneeReason}，<b>明确告知送没送到、送给了谁</b></td></tr>
 *   <tr><td>{@code GET /api/v1/feedback/mine}</td><td>提交人</td><td>我的提交记录（含答复）</td></tr>
 *   <tr><td>{@code GET /api/v1/feedback/inbox}</td><td>接收人（本部门管理员）</td><td>「收到的建议」</td></tr>
 *   <tr><td>{@code POST /api/v1/feedback/{id}/reply}</td><td>接收人</td><td>回复；提交人收到站内通知</td></tr>
 * </table>
 *
 * <p><b>为什么提交接口不是 201 + Location，而是 200 带业务字段</b>：本项目的响应口径统一为
 * {@code ApiResponse}（{@code code/message/data}），前端 {@code unwrap} 依赖 {@code code} 判定成败。
 * 单独给这个接口换个语义会破坏统一约定，且「是否送达」是<b>业务结果</b>而不是 HTTP 语义
 * —— 送达失败并不是请求失败（记录已落库）。</p>
 */
@RestController
@RequestMapping("/api/v1/feedback")
@RequiredArgsConstructor
public class FeedbackController {

    private final FeedbackService feedbackService;

    /** 提交投诉 / 建议。{@code delivered=false} 表示记录已存但无人可派（不是提交失败）。 */
    @PostMapping
    public ApiResponse<Map<String, Object>> submit(@RequestBody Map<String, Object> body) {
        return ApiResponse.ok(feedbackService.submit(AuthUserContext.require(), body));
    }

    /** 我提交过的反馈（含管理员答复）。 */
    @GetMapping("/mine")
    public ApiResponse<Map<String, Object>> mine() {
        return ApiResponse.ok(feedbackService.mine(AuthUserContext.require()));
    }

    /** 派给我的反馈（「收到的建议」）。只有接收人本人可见。 */
    @GetMapping("/inbox")
    public ApiResponse<Map<String, Object>> inbox(
            @RequestParam(name = "status", required = false) String status) {
        return ApiResponse.ok(feedbackService.inbox(AuthUserContext.require(), status));
    }

    /** 回复一条反馈。提交人会收到站内通知。 */
    @PostMapping("/{id}/reply")
    public ApiResponse<Map<String, Object>> reply(@PathVariable Long id,
                                                  @RequestBody Map<String, Object> body) {
        return ApiResponse.ok(feedbackService.reply(AuthUserContext.require(), id, body));
    }
}
