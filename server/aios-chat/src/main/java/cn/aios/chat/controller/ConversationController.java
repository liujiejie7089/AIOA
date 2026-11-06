package cn.aios.chat.controller;

import cn.aios.chat.dto.CreateConversationRequest;
import cn.aios.chat.dto.CreateRunRequest;
import cn.aios.chat.dto.RenameConversationRequest;
import cn.aios.chat.dto.RunCreatedResponse;
import cn.aios.chat.entity.ChatConversation;
import cn.aios.chat.entity.ChatMessage;
import cn.aios.chat.service.ConversationService;
import cn.aios.chat.service.RunService;
import cn.aios.common.resp.ApiResponse;
import cn.aios.common.resp.PageResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
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

import java.util.List;

@Tag(name = "会话")
@RestController
@RequestMapping("/api/v1/conversations")
@RequiredArgsConstructor
public class ConversationController {

    private final ConversationService conversationService;
    private final RunService runService;

    @Operation(summary = "创建会话")
    @PostMapping
    public ApiResponse<ChatConversation> create(@RequestBody(required = false) CreateConversationRequest request) {
        String title = request == null ? null : request.getTitle();
        String appCode = request == null ? null : request.getAppCode();
        Long workerId = request == null ? null : request.getWorkerId();
        Long projectId = request == null ? null : request.getProjectId();
        return ApiResponse.ok(conversationService.create(title, appCode, workerId, projectId));
    }

    @Operation(summary = "会话列表（分页/搜索/按项目过滤）")
    @GetMapping
    public ApiResponse<PageResult<ChatConversation>> list(
            @RequestParam(name = "page", defaultValue = "1") long page,
            @RequestParam(name = "size", defaultValue = "20") long size,
            @RequestParam(name = "keyword", required = false) String keyword,
            @RequestParam(name = "projectId", required = false) Long projectId,
            // onlyAsked=true：只返回已经提过问的会话（用户端「最近」用），默认 false 兼容旧调用
            @RequestParam(name = "onlyAsked", defaultValue = "false") boolean onlyAsked) {
        return ApiResponse.ok(conversationService.page(page, size, keyword, projectId, onlyAsked));
    }

    @Operation(summary = "会话详情")
    @GetMapping("/{id}")
    public ApiResponse<ChatConversation> detail(@PathVariable Long id) {
        return ApiResponse.ok(conversationService.getOwned(id));
    }

    @Operation(summary = "删除会话（逻辑删除）")
    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        conversationService.delete(id);
        return ApiResponse.ok();
    }

    @Operation(summary = "重命名会话（FR-D3）")
    @PutMapping("/{id}")
    public ApiResponse<Void> rename(@PathVariable Long id,
                                    @RequestBody(required = false) RenameConversationRequest request) {
        conversationService.rename(id, request == null ? null : request.getTitle());
        return ApiResponse.ok();
    }

    @Operation(summary = "置顶 / 取消置顶会话（长按菜单）")
    @PutMapping("/{id}/pin")
    public ApiResponse<Void> pin(@PathVariable Long id,
                                 @RequestBody(required = false) java.util.Map<String, Object> body) {
        // 缺省视为「置顶」：前端长按菜单点在「置顶」上，传 {"pinned":true}；
        // 不传时按置顶处理更符合直觉（误触后再点一次「取消置顶」即可，幂等）。
        Object v = body == null ? null : body.get("pinned");
        boolean pinned = v == null || Boolean.parseBoolean(String.valueOf(v));
        conversationService.pin(id, pinned);
        return ApiResponse.ok();
    }

    @Operation(summary = "会话消息（游标分页，beforeSeq 向前翻）")
    @GetMapping("/{id}/messages")
    public ApiResponse<List<ChatMessage>> messages(
            @PathVariable Long id,
            @RequestParam(name = "beforeSeq", required = false) Long beforeSeq,
            @RequestParam(name = "size", defaultValue = "30") Integer size) {
        return ApiResponse.ok(conversationService.messages(id, beforeSeq, size));
    }

    @Operation(summary = "会话内切换数字人（越界建议卡「转过去处理」）")
    @PostMapping("/{id}/handoff")
    public ApiResponse<java.util.Map<String, Object>> handoff(
            @PathVariable Long id,
            @RequestBody(required = false) java.util.Map<String, Object> body) {
        // 与 run 前的自动转交共用 rebindWorker（同租户 / 未停用 / 项目可分配 三重校验在 bindWorker 里）。
        // **只改绑、不新建会话**：换会话会丢历史，新数字人接不住同一句原话（见 rebindWorker 注释）。
        Object v = body == null ? null : body.get("workerId");
        if (v == null || String.valueOf(v).isBlank()) {
            throw cn.aios.common.exception.BizException.badRequest("workerId 不能为空");
        }
        Long workerId;
        try {
            workerId = Long.valueOf(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            throw cn.aios.common.exception.BizException.badRequest("workerId 非法：" + v);
        }
        ChatConversation conversation = conversationService.getOwned(id);
        conversationService.rebindWorker(conversation, workerId);
        java.util.Map<String, Object> out = new java.util.LinkedHashMap<>();
        out.put("conversationId", id);
        out.put("workerId", workerId);
        return ApiResponse.ok(out);
    }

    @Operation(summary = "发起一轮对话（返回 runId，随后用 SSE 订阅事件）")
    @PostMapping("/{id}/runs")
    public ApiResponse<RunCreatedResponse> createRun(@PathVariable Long id,
                                                     @RequestBody CreateRunRequest request) {
        String text = request == null ? null : request.getText();
        String runId = runService.start(id, text,
                request == null ? null : request.getContext(),
                request == null ? null : request.getAttachments(),
                request == null ? null : request.getModelRef(),
                request == null ? null : request.getKbOn(),
                request == null ? null : request.getExpertKey(),
                request == null ? null : request.getExpert(),
                request == null ? null : request.getDisabledConnectors(),
                request == null ? null : request.getCredentialId());
        return ApiResponse.ok(new RunCreatedResponse(runId));
    }
}
