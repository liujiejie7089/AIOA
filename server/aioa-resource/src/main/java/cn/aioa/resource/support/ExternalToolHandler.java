package cn.aioa.resource.support;

import cn.aioa.security.AuthUser;

import java.util.Map;
import java.util.Set;

/**
 * 外部业务工具扩展点（V36）。
 *
 * <p>{@code ToolGatewayService} 的工具注册表是静态白名单，工具实现必须落在
 * {@code aioa-resource} 内。但「权限申请」这类工具的领域归属在 {@code aioa-org}
 * （审批引擎所在模块），而 {@code aioa-resource} <b>不依赖</b> {@code aioa-org}（兄弟模块）。</p>
 *
 * <p>做法与既有 {@code ApprovalCallback} 一致：本模块只定义接口，
 * 由 {@code aioa-boot} 组装时把各业务模块的实现注入进来。运行时 Spring 上下文里有谁就用谁，
 * 编译期零耦合；裁剪掉某模块时工具自动消失，网关无需改动。</p>
 *
 * <p><b>实现方约定</b>：</p>
 * <ul>
 *   <li>{@link #name()} 必须全局唯一，与静态注册表里的工具名冲突时以静态注册表为准；</li>
 *   <li>{@link #invoke} 以「当前登录用户」身份执行（网关透传用户上下文），越权天然不可达；</li>
 *   <li>业务失败<b>不要抛异常</b>，返回 {@code {ok:false, error:"..."}} 由模型组织回答 —— 与静态工具一致。</li>
 * </ul>
 */
public interface ExternalToolHandler {

    /** 工具名（OpenAI function name，需符合 [a-zA-Z0-9_-]）。 */
    String name();

    /** 工具描述：模型据此判断何时调用，必须写清适用场景。 */
    String description();

    /** 参数 JSON Schema（OpenAI function parameters 格式）。 */
    String parametersJson();

    /** 调用所需角色（空集合 = 任意登录用户）。 */
    default Set<String> requiredRoles() {
        return Set.of();
    }

    /**
     * 执行工具。
     *
     * @param args 模型给出的参数（可能为 null）
     * @param user 当前登录用户（网关透传）
     * @return {@code {ok:true, data:...}} 或 {@code {ok:false, error:"..."}}
     */
    Map<String, Object> invoke(Map<String, Object> args, AuthUser user);
}
