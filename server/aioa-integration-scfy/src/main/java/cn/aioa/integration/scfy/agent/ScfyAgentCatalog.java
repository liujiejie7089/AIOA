package cn.aioa.integration.scfy.agent;

import cn.aioa.integration.scfy.ScfyAutoConfiguration;
import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.contract.ScfyResultEnvelope;
import cn.aioa.tool.sdk.LocalToolRegistry;
import cn.aioa.tool.sdk.ToolSpec;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * agent 侧的接口注册表 —— 「哪些接口可以给 agent 用、各是什么」的唯一事实源。
 *
 * <p><b>它是三份事实的联结，自己不产生事实</b>：</p>
 * <table border="1">
 *   <caption>注册项各字段的来源</caption>
 *   <tr><th>要素</th><th>来源</th><th>为什么从这里取</th></tr>
 *   <tr><td>名称 / 用途描述 / 入参 Schema</td><td>{@code @AioaTool} 注解（经 SDK 注册表）</td>
 *       <td>与模型看到的工具清单同源，不可能出现「注册表说三个参数、清单说两个」</td></tr>
 *   <tr><td>分组 / 路径 / 参数契约（必填性、枚举、实测校正）</td><td>{@link ScfyCatalog}</td>
 *       <td>接口事实只在契约里判定一处</td></tr>
 *   <tr><td>返回结构</td><td>{@code resources/scfy/return-shape.json}（矩阵实测生成）</td>
 *       <td>手写返回结构等于第二份真相，后端改字段名之后它会静默变成误导</td></tr>
 * </table>
 *
 * <p><b>新增一个接口要改哪里</b>：加一行契约（{@link ScfyCatalog}）+ 一个
 * {@code @AioaTool} 方法，再跑一次矩阵把返回结构采回来。<b>本类、匹配器、调用器都不需要改</b> ——
 * 这正是「可扩展」要保证的东西：扩展点在数据与注解上，不在流程代码里。</p>
 */
public class ScfyAgentCatalog {

    private static final Logger log = LoggerFactory.getLogger(ScfyAgentCatalog.class);

    /** 矩阵实测生成的返回结构资源（由 {@code ScfyMatrixTest} 写入）。 */
    public static final String SHAPE_RESOURCE = "/scfy/return-shape.json";

    /** agent 层自身的工具编码 —— 它们不映射任何 scfy 接口，登记在契约之外。 */
    public static final String ASK_TOOL_CODE = "scfy_ask";
    public static final String CATALOG_TOOL_CODE = "scfy_catalog";
    public static final Set<String> AGENT_LAYER_TOOL_CODES = Set.of(ASK_TOOL_CODE, CATALOG_TOOL_CODE);

    private final List<ScfyToolDescriptor> all;
    private final Map<String, ScfyToolDescriptor> byToolCode;
    private final Map<String, ScfyToolDescriptor> byEndpointId;
    /** 工具指向了契约里不存在的接口（代码缺陷，启动自检据此拒绝启动）。 */
    private final List<String> dangling;
    /** 契约可用但还没有工具的接口（分阶段接入的正常状态，只告警）。 */
    private final List<String> toolMissing;
    private final Map<String, Object> shapeMeta;

    private ScfyAgentCatalog(List<ScfyToolDescriptor> all,
                             Map<String, ScfyToolDescriptor> byToolCode,
                             Map<String, ScfyToolDescriptor> byEndpointId,
                             List<String> dangling,
                             List<String> toolMissing,
                             Map<String, Object> shapeMeta) {
        this.all = List.copyOf(all);
        this.byToolCode = Map.copyOf(byToolCode);
        this.byEndpointId = Map.copyOf(byEndpointId);
        this.dangling = List.copyOf(dangling);
        this.toolMissing = List.copyOf(toolMissing);
        this.shapeMeta = shapeMeta == null ? Map.of() : Map.copyOf(shapeMeta);
    }

    // ==================== 装配 ====================

    /** 从 classpath 读取返回结构资源并装配。 */
    public static ScfyAgentCatalog load(LocalToolRegistry registry, ObjectMapper mapper) {
        return load(registry, readShapeResource(mapper));
    }

    /**
     * 用给定的返回结构根节点装配（测试可直接注入，不依赖 classpath）。
     *
     * @param shapeRoot {@code return-shape.json} 的内容；可为 null（此时所有接口的返回结构都缺失，
     *                  启动自检会据此响亮失败）
     */
    @SuppressWarnings("unchecked")
    public static ScfyAgentCatalog load(LocalToolRegistry registry, Map<String, Object> shapeRoot) {
        Map<String, Map<String, Object>> shapes = new LinkedHashMap<>();
        Map<String, Object> meta = new LinkedHashMap<>();
        if (shapeRoot != null) {
            Object eps = shapeRoot.get("endpoints");
            if (eps instanceof Map<?, ?> m) {
                for (Map.Entry<?, ?> e : m.entrySet()) {
                    if (e.getValue() instanceof Map<?, ?> v) {
                        shapes.put(String.valueOf(e.getKey()), (Map<String, Object>) v);
                    }
                }
            }
            for (Map.Entry<String, Object> e : shapeRoot.entrySet()) {
                if (!"endpoints".equals(e.getKey())) {
                    meta.put(e.getKey(), e.getValue());
                }
            }
        }

        List<ScfyToolDescriptor> all = new ArrayList<>();
        Map<String, ScfyToolDescriptor> byCode = new LinkedHashMap<>();
        Map<String, ScfyToolDescriptor> byEndpoint = new LinkedHashMap<>();
        List<String> dangling = new ArrayList<>();
        Set<String> covered = new LinkedHashSet<>();

        for (ToolSpec spec : sortByCode(registry.all())) {
            String code = spec.toolCode();
            if (code == null || !code.startsWith(ScfyAutoConfiguration.TOOL_PREFIX)) {
                continue;
            }
            if (AGENT_LAYER_TOOL_CODES.contains(code)) {
                continue;
            }
            String endpointId = code.substring(ScfyAutoConfiguration.TOOL_PREFIX.length());
            ScfyEndpoint ep = ScfyCatalog.byId(endpointId);
            if (ep == null) {
                dangling.add("工具 " + code + " 指向契约中不存在的接口「" + endpointId + "」");
                continue;
            }
            if (!ep.available()) {
                dangling.add("工具 " + code + " 指向已废弃接口：" + ep.note());
                continue;
            }
            covered.add(endpointId);
            Map<String, Object> shape = shapes.get(endpointId);
            ScfyToolDescriptor d = new ScfyToolDescriptor(
                    code,
                    endpointId,
                    ep.group(),
                    spec.displayName(),
                    spec.description(),
                    ep.fullPath(),
                    ep.params(),
                    spec.inputSchema(),
                    ScfyResultEnvelope.schema(shape),
                    shape,
                    shape == null ? "UNKNOWN" : String.valueOf(shape.getOrDefault("observed", "UNKNOWN")));
            all.add(d);
            byCode.put(code, d);
            byEndpoint.put(endpointId, d);
        }

        List<String> toolMissing = new ArrayList<>();
        for (ScfyEndpoint ep : ScfyCatalog.available()) {
            if (!covered.contains(ep.id())) {
                toolMissing.add(ep.id() + "（" + ep.group() + "）");
            }
        }
        log.info("scfy agent 注册表：{} 个接口（可直接匹配的 {} 个，恒空被排除的 {} 个）；"
                        + "返回结构来源 observed={}",
                all.size(), countData(all), all.size() - countData(all), meta.get("generatedFrom"));
        return new ScfyAgentCatalog(all, byCode, byEndpoint, dangling, toolMissing, meta);
    }

    private static List<ToolSpec> sortByCode(java.util.Collection<ToolSpec> specs) {
        List<ToolSpec> list = new ArrayList<>(specs);
        list.sort((a, b) -> String.valueOf(a.toolCode()).compareTo(String.valueOf(b.toolCode())));
        return list;
    }

    private static int countData(List<ScfyToolDescriptor> ds) {
        int n = 0;
        for (ScfyToolDescriptor d : ds) {
            if (d.returnsData()) {
                n++;
            }
        }
        return n;
    }

    /** 读 classpath 里的返回结构资源；缺失即抛，并给出可执行的补救指令。 */
    static Map<String, Object> readShapeResource(ObjectMapper mapper) {
        try (InputStream in = ScfyAgentCatalog.class.getResourceAsStream(SHAPE_RESOURCE)) {
            if (in == null) {
                throw new IllegalStateException("缺少返回结构资源 " + SHAPE_RESOURCE
                        + "。它是实测生成的，不能用空文件糊过去：请先跑 "
                        + "`mvn -pl aioa-integration-scfy test -Dtest=ScfyMatrixTest -Dscfy.matrix=true` 生成。");
            }
            return mapper.readValue(in, new TypeReference<Map<String, Object>>() {
            });
        } catch (IOException e) {
            throw new IllegalStateException("返回结构资源 " + SHAPE_RESOURCE + " 解析失败：" + e.getMessage(), e);
        }
    }

    // ==================== 查询 ====================

    /** 全部已注册接口（含恒空的那个，它在清单里可见、但不参与自动匹配）。 */
    public List<ScfyToolDescriptor> all() {
        return all;
    }

    /**
     * 可用于「语义匹配 + 自动调用」的接口 —— 即<b>已实测能返回数据</b>的那些。
     *
     * <p>把恒空的接口排除在自动匹配之外：它调用成功、code=0、却不给任何数据，
     * 用户会得到「查到了，但没有结果」这种无法判断真假的回答。它仍留在
     * {@link #all()} 与 {@code scfy_catalog} 里，并写明被排除的原因，
     * 而不是从清单上消失（消失就没人知道它为什么不在）。</p>
     */
    public List<ScfyToolDescriptor> registered() {
        List<ScfyToolDescriptor> out = new ArrayList<>();
        for (ScfyToolDescriptor d : all) {
            if (d.returnsData()) {
                out.add(d);
            }
        }
        return out;
    }

    /** 契约可用但实测恒空、故不参与自动匹配的接口。 */
    public List<ScfyToolDescriptor> excluded() {
        List<ScfyToolDescriptor> out = new ArrayList<>();
        for (ScfyToolDescriptor d : all) {
            if (!d.returnsData()) {
                out.add(d);
            }
        }
        return out;
    }

    public ScfyToolDescriptor byToolCode(String toolCode) {
        return toolCode == null ? null : byToolCode.get(toolCode);
    }

    public ScfyToolDescriptor byEndpointId(String endpointId) {
        return endpointId == null ? null : byEndpointId.get(endpointId);
    }

    public int size() {
        return all.size();
    }

    /** 工具指向了契约外/已废弃接口 —— 代码缺陷。 */
    public List<String> dangling() {
        return dangling;
    }

    /** 契约可用但还没有工具的接口。 */
    public List<String> toolMissing() {
        return toolMissing;
    }

    public Map<String, Object> shapeMeta() {
        return shapeMeta;
    }

    /** 四要素齐备性自检结果：接口 id → 缺失项。空 Map 表示全部齐备。 */
    public Map<String, List<String>> incompleteness() {
        Map<String, List<String>> bad = new TreeMap<>();
        for (ScfyToolDescriptor d : all) {
            List<String> miss = d.missingParts();
            if (!miss.isEmpty()) {
                bad.put(d.endpointId(), miss);
            }
        }
        return bad;
    }
}
