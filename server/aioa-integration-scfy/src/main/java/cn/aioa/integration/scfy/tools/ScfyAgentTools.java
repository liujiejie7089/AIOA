package cn.aioa.integration.scfy.tools;

import cn.aioa.integration.scfy.agent.ScfyAgentCatalog;
import cn.aioa.integration.scfy.agent.ScfyAgentService;
import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * agent 侧的两个入口工具 —— 让「注册」与「语义匹配」在现有工具机制下即可用。
 *
 * <p><b>为什么是这两个工具，而不是新加一套 HTTP 接口</b>：本模块的既有口径是
 * 「适配器不做 Controller、不占端口」，能力的对外通道统一由平台工具网关提供
 * （{@code /internal/v1/tools} 列表 + {@code /internal/v1/tools/invoke} 调用）。
 * 用 {@code @AioaTool} 声明两个方法，就自动获得了清单登记、权限、审计、
 * 与其余 55 个工具一致的调用方式 —— 不需要在基座上开新口子，也不需要改基座一行代码。</p>
 *
 * <p>两个工具的分工：</p>
 * <ul>
 *   <li>{@code scfy_ask} —— <b>一句话直达数据</b>。适合「用户直接问非遗问题」的主流程：
 *       服务端负责语义匹配、参数抽取、调用与裁剪，模型只需把用户原话递进来。</li>
 *   <li>{@code scfy_catalog} —— <b>先看清单再决定</b>。返回每个接口的名称、用途、参数与返回结构；
 *       适合需要精确控制调用哪个接口、或要确认字段名的场景。</li>
 * </ul>
 *
 * <p>二者都只读：{@code scfy_ask} 只会调契约中标记为可用的查询接口，
 * 不存在任何写路径（写方法在 {@code ScfyClient} 里根本不存在）。</p>
 */
@Component
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyAgentTools {

    private final ScfyAgentService service;

    public ScfyAgentTools(ScfyAgentService service) {
        this.service = service;
    }

    @AioaTool(code = ScfyAgentCatalog.ASK_TOOL_CODE,
            name = "非遗-自然语言查询",
            description = "用一句自然语言查询四川省非遗数据，服务端负责把它匹配到合适的非遗接口、"
                    + "补全参数并返回结果。凡用户问非遗相关问题（有哪些非遗项目 / 某地有多少传承人 / "
                    + "非遗工坊的销量 / 文化生态保护区 / 非遗旅游线路与体验基地 / 某个非遗的详情等），"
                    + "优先用它，把用户原话整句传进来（保留地名、等级、数量等词，不要改写）。"
                    + "若返回 matched=false，说明问题与本系统可查范围无关，请如实转述原因而不是编造数据。"
                    + "若返回 needUserInput=true，把 askUser 的追问话术转述给用户补充信息后再查。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> ask(
            @AioaToolParam(name = "question",
                    description = "用户原话，例如「成都有哪些非遗工坊」「甘孜州有多少非遗项目」"
                            + "「安岳石刻的详情」；整句传入，不要自行拆解或改写",
                    required = true) String question,
            @AioaToolParam(name = "toolCode",
                    description = "可选：已知要调用哪个接口时直接指定（形如 scfy_project_list_by_area），"
                            + "指定后跳过语义匹配。不确定就留空",
                    required = false) String toolCode) {
        return service.ask(question, toolCode);
    }

    @AioaTool(code = ScfyAgentCatalog.CATALOG_TOOL_CODE,
            name = "非遗-接口清单",
            description = "列出非遗系统已注册的查询接口，每个接口给出：名称、用途描述、参数（含必填性与可选值）、"
                    + "以及返回结构（真实字段名，来自生产实测）。两种用法："
                    + "①不传参数 —— 看全部接口的概览，用于确认「这个问题到底能不能查」；"
                    + "②传 toolCode —— 看某个接口的完整参数表与返回字段，用于精确取值。"
                    + "注意：清单里标注 observed 非 OK_DATA 的接口调用成功但不返回数据，不要用它回答用户。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> catalog(
            @AioaToolParam(name = "group",
                    description = "可选：只看某个能力域，取值为 传承人 / 项目 / 工坊 / 保护区 / 旅游",
                    required = false) String group,
            @AioaToolParam(name = "keyword",
                    description = "可选：按关键词过滤接口（匹配名称、用途、参数说明、返回字段）",
                    required = false) String keyword,
            @AioaToolParam(name = "toolCode",
                    description = "可选：查看某个接口的完整信息（参数明细 + 返回结构），传了它则忽略 group/keyword",
                    required = false) String toolCode) {
        if (toolCode != null && !toolCode.isBlank()) {
            return service.describe(toolCode);
        }
        return service.catalogList(group, keyword);
    }
}
