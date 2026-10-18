package cn.aios.chat.controller;

import cn.aios.chat.service.RunService;
import cn.aios.common.resp.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Tag(name = "Agent 运行")
@RestController
@RequiredArgsConstructor
public class RunController {

    private final RunService runService;

    @Operation(summary = "SSE 事件流（Java 中转 Python，支持 Last-Event-ID 续传）")
    @GetMapping(path = "/api/v1/runs/{runId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@PathVariable String runId,
                             @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId,
                             @RequestHeader(value = "Authorization", required = false) String authorization) {
        return runService.subscribe(runId, lastEventId, authorization);
    }

    @Operation(summary = "多任务协同：执行一份显式计划（子任务 + 依赖 + 入参引用），SSE 事件流")
    @PostMapping(path = "/api/v1/agent/tasks", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter runTasks(@RequestBody Map<String, Object> body,
                               @RequestHeader(value = "Authorization", required = false) String authorization) {
        return runService.runTasks(body, authorization);
    }

    @Operation(summary = "中断运行")
    @PostMapping("/api/v1/runs/{runId}/cancel")
    public ApiResponse<Void> cancel(@PathVariable String runId) {
        runService.cancel(runId);
        return ApiResponse.ok();
    }

    @Operation(summary = "HITL 澄清回填：把澄清卡选择送回 agent，从断点续跑（SSE 事件流）")
    @PostMapping(path = "/api/v1/runs/{runId}/resume", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter resume(@PathVariable String runId,
                             @RequestBody(required = false) Map<String, Object> body,
                             @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId,
                             @RequestHeader(value = "Authorization", required = false) String authorization) {
        return runService.resume(runId, body, lastEventId, authorization);
    }
}
