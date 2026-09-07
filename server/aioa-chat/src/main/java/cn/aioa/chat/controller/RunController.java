package cn.aioa.chat.controller;

import cn.aioa.chat.service.RunService;
import cn.aioa.common.resp.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Tag(name = "Agent 运行")
@RestController
@RequiredArgsConstructor
public class RunController {

    private final RunService runService;

    @Operation(summary = "SSE 事件流（Java 中转 Python，支持 Last-Event-ID 续传）")
    @GetMapping(path = "/api/v1/runs/{runId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@PathVariable String runId,
                             @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId) {
        return runService.subscribe(runId, lastEventId);
    }

    @Operation(summary = "中断运行")
    @PostMapping("/api/v1/runs/{runId}/cancel")
    public ApiResponse<Void> cancel(@PathVariable String runId) {
        runService.cancel(runId);
        return ApiResponse.ok();
    }
}
