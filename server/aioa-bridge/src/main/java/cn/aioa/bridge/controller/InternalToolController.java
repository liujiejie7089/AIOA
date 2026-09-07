package cn.aioa.bridge.controller;

import cn.aioa.common.resp.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.Data;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 工具桥接内部接口：M1 占位，固定返回 501（M2 实现真实调用）。
 */
@Tag(name = "内部-工具桥接")
@RestController
@RequestMapping("/internal/v1/tools")
public class InternalToolController {

    @Operation(summary = "工具调用（M1 未实现）")
    @PostMapping("/invoke")
    public ApiResponse<Void> invoke(@RequestBody(required = false) ToolInvokeRequest request) {
        throw cn.aioa.common.exception.BizException.notImplemented("tool invoke 将在 M2 实现");
    }

    @Data
    public static class ToolInvokeRequest {

        private String toolCode;
        private String version;
        private String runId;
        private java.util.Map<String, Object> args;
    }
}
