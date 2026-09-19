package cn.aioa.bridge.tool;

import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import cn.aioa.tool.sdk.ToolCallContext;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 服务内工具示例：证明「写一个带注解的方法 = 注册一个受治理的工具」。
 *
 * <p>这两个工具不与任何外部系统通信，纯粹用于自检与验收：
 * 它们让「注解 → 工具定义 → 权限/审批/幂等闸门 → 执行 → 审计」这条链路
 * 可以在不依赖任何外部依赖的情况下被完整验证。</p>
 *
 * <p>注意 {@code platform_self_check_approval} —— 它标了
 * {@link AioaTool#requiresApproval()}=true：本地方法同样要过审批闸门。
 * 「本地实现」不是绕过治理的理由，这正是注解式工具的危险之处：
 * 若把绕过当便利，高风险操作会从注解通道悄悄漏过去。</p>
 */
@Component
public class PlatformSelfCheckTools {

    public static final String TOOL_SELF_CHECK = "platform_self_check";
    public static final String TOOL_SELF_CHECK_APPROVAL = "platform_self_check_approval";

    @AioaTool(
            code = TOOL_SELF_CHECK,
            name = "平台自检",
            description = "对平台自身做一次只读自检，返回调用者身份、传入参数与检查时间。"
                    + "用于验证工具桥接链路是否连通，不产生任何副作用。",
            domain = "platform",
            riskLevel = "LOW",
            owner = "platform")
    public Map<String, Object> selfCheck(
            @AioaToolParam(name = "scope", description = "自检范围，可空；如 gateway / org", required = false)
            String scope,
            @AioaToolParam(name = "rounds", description = "重复自检轮次，缺省 1", required = false,
                    type = "integer")
            Integer rounds,
            ToolCallContext caller) {

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("scope", scope == null ? "all" : scope);
        data.put("rounds", rounds == null ? 1 : rounds);
        data.put("callerUserId", caller == null ? null : caller.userId());
        data.put("callerTenantId", caller == null ? null : caller.tenantId());
        data.put("callerUsername", caller == null ? null : caller.username());
        data.put("checkedAt", LocalDateTime.now().toString());
        data.put("impl", "aioa-bridge/platform_self_check（服务内，未出网）");

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("data", data);
        return out;
    }

    @AioaTool(
            code = TOOL_SELF_CHECK_APPROVAL,
            name = "平台自检（高危，需审批）",
            description = "与平台自检同源，但被标记为高风险：调用不会立即执行，"
                    + "需企业管理员审批通过后才由回调恢复执行。",
            domain = "platform",
            riskLevel = "HIGH",
            requiresApproval = true,
            owner = "platform")
    public Map<String, Object> selfCheckGuarded(
            @AioaToolParam(name = "scope", description = "自检范围，可空", required = false) String scope,
            ToolCallContext caller) {

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("scope", scope == null ? "all" : scope);
        data.put("callerUserId", caller == null ? null : caller.userId());
        data.put("approved", true);
        data.put("checkedAt", LocalDateTime.now().toString());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("data", data);
        return out;
    }
}
