package cn.aioa.chat.controller;

import cn.aioa.chat.dto.CreateConversationRequest;
import cn.aioa.chat.dto.CreateRunRequest;
import cn.aioa.chat.dto.RenameConversationRequest;
import cn.aioa.chat.dto.RunCreatedResponse;
import cn.aioa.chat.entity.ChatConversation;
import cn.aioa.chat.entity.ChatMessage;
import cn.aioa.chat.service.ConversationService;
import cn.aioa.chat.service.RunService;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.common.resp.PageResult;
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
        return ApiResponse.ok(conversationService.create(title, appCode));
    }

    @Operation(summary = "会话列表（分页/搜索）")
    @GetMapping
    public ApiResponse<PageResult<ChatConversation>> list(
            @RequestParam(name = "page", defaultValue = "1") long page,
            @RequestParam(name = "size", defaultValue = "20") long size,
            @RequestParam(name = "keyword", required = false) String keyword) {
        return ApiResponse.ok(conversationService.page(page, size, keyword));
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

    @Operation(summary = "会话消息（游标分页，beforeSeq 向前翻）")
    @GetMapping("/{id}/messages")
    public ApiResponse<List<ChatMessage>> messages(
            @PathVariable Long id,
            @RequestParam(name = "beforeSeq", required = false) Long beforeSeq,
            @RequestParam(name = "size", defaultValue = "30") Integer size) {
        return ApiResponse.ok(conversationService.messages(id, beforeSeq, size));
    }

    @Operation(summary = "发起一轮对话（返回 runId，随后用 SSE 订阅事件）")
    @PostMapping("/{id}/runs")
    public ApiResponse<RunCreatedResponse> createRun(@PathVariable Long id,
                                                     @RequestBody CreateRunRequest request) {
        String text = request == null ? null : request.getText();
        String runId = runService.start(id, text,
                request == null ? null : request.getContext(),
                request == null ? null : request.getAttachments(),
                request == null ? null : request.getModelRef());
        return ApiResponse.ok(new RunCreatedResponse(runId));
    }
}
