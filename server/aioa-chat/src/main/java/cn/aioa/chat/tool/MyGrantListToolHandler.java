package cn.aioa.chat.tool;

import cn.aioa.org.service.PermissionGrantService;
import cn.aioa.resource.support.ExternalToolHandler;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * 「查询我的权限申请」工具（V36 需求①闭环的另一半）。
 *
 * <p>只给提交入口、不给查询入口，用户问「我申请到哪一步了」时模型只能答「请到页面查看」，
 * 「通过 AI 完成整个流程」就断在最后一环。故与 {@link PermissionGrantToolHandler} 成对注册。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class MyGrantListToolHandler implements ExternalToolHandler {

    private final PermissionGrantService grantService;

    @Override
    public String name() {
        return PermissionGrantToolHandler.TOOL_LIST;
    }

    @Override
    public String description() {
        return "查询当前用户提交过的权限申请及其状态（待审 / 已生效 / 已驳回 / 已回收），"
                + "以及我已持有的权限。用户问「我的权限申请到哪了」「我有哪些权限」时调用。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            List<Map<String, Object>> applies = grantService.mine(user);
            List<Map<String, Object>> holdings = grantService.holdings(user);
            return Map.of("ok", true, "data", Map.of(
                    "applies", applies,
                    "holdings", holdings,
                    "count", applies.size()));
        } catch (Exception e) {
            return Map.of("ok", false, "error", String.valueOf(e.getMessage()));
        }
    }
}
