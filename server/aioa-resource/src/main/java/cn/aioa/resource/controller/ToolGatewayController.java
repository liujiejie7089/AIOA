package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.service.ToolGatewayService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 业务工具网关：智能体（携带用户 token）调用业务系统接口的统一入口。
 * 权限模型：工具权限 = 用户权限（Agent 透传用户 token，越权数据天然不可达）。
 */
@RestController
@RequestMapping("/api/v1/tools")
public class ToolGatewayController {

    private final ToolGatewayService toolGatewayService;

    public ToolGatewayController(ToolGatewayService toolGatewayService) {
        this.toolGatewayService = toolGatewayService;
    }

    /** 工具清单（OpenAI function-calling 格式，供 Agent 注入模型）。 */
    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list() {
        AuthUserContext.require();
        return ApiResponse.ok(toolGatewayService.listTools());
    }

    /** 执行工具（以当前用户身份）。 */
    @PostMapping("/invoke")
    public ApiResponse<Map<String, Object>> invoke(@RequestBody InvokeReq req) {
        AuthUser user = AuthUserContext.require();
        if (req.name() == null || req.name().isBlank()) {
            throw BizException.badRequest("name 不能为空");
        }
        return ApiResponse.ok(toolGatewayService.invoke(req.name(), req.arguments(), user));
    }

    public record InvokeReq(String name, Map<String, Object> arguments) {
    }
}
