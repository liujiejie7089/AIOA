package cn.aioa.integration.scfy.tools;

import cn.aioa.integration.scfy.adapter.ScfyClient;
import cn.aioa.integration.scfy.adapter.ScfyResponse;
import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.contract.ScfyEndpoint;
import cn.aioa.integration.scfy.contract.ScfyParam;
import cn.aioa.integration.scfy.contract.ScfyResultEnvelope;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工具层公共支撑 —— 每个工具方法只声明「调哪个接口」，其余一律走这里。
 *
 * <p>把「查契约 → 校验 → 调用 → 裁剪 → 组装结果」收成一条路径，
 * 是为了避免每个工具各自实现一遍而漂移出同样多种失败语义。
 * 尤其是<b>失败必须结构化返回</b>：工具不抛异常给模型，而是返回
 * {@code ok=false} + 可读原因 + 下一步建议，否则模型只能看到「调用失败」四个字，
 * 然后开始瞎试。</p>
 *
 * <p><b>裁剪</b>：scfy 有些接口一次返回上千条（如工坊地图分布 type1 有 35 条、
 * 传承人列表全省 1821 条）。不裁剪就会把上下文撑爆，且模型也用不上。
 * 裁剪时明确标注 {@code truncated=true} 与实际总数，
 * 让模型知道「这不是全部」—— 静默截断是缺陷（参考 KB 列表那次），不是优化。</p>
 *
 * <p><b>信封键名一律取自 {@link ScfyResultEnvelope}</b>，不再写字面量：
 * 「返回结构」要对外声明给模型看，若实现与声明各写一份，模型会照着不存在的字段取值。
 * 用常量把这层锁死，声明与产出就不可能不一致。</p>
 */
public class ScfyToolSupport {

    private static final Logger log = LoggerFactory.getLogger(ScfyToolSupport.class);

    /** 单次返回给模型的最大条目数。 */
    private static final int MAX_ITEMS = 50;

    private final ScfyClient client;
    private final ScfyParamValidator validator;

    public ScfyToolSupport(ScfyClient client, ScfyParamValidator validator) {
        this.client = client;
        this.validator = validator;
    }

    /**
     * 统一的工具执行入口。
     *
     * @param endpointId 契约中的接口 id
     * @param params     模型给出的参数
     */
    public Map<String, Object> call(String endpointId, Map<String, Object> params) {
        ScfyEndpoint ep = ScfyCatalog.byId(endpointId);
        if (ep == null) {
            // 契约不存在 = 代码缺陷（工具声明了目录里没有的 id），必须响亮失败
            throw new IllegalStateException(
                    "工具声明的接口 id「" + endpointId + "」不在 ScfyCatalog 中 —— 工具与契约已漂移");
        }

        ScfyParamValidator.Result vr = validator.validate(ep, params);
        if (!vr.ok()) {
            Map<String, Object> out = base(ep);
            out.put(ScfyResultEnvelope.OK, false);
            if (vr.askUser() != null) {
                out.put(ScfyResultEnvelope.NEED_USER_INPUT, true);
                out.put(ScfyResultEnvelope.ASK_USER, vr.askUser());
            }
            if (!vr.errors().isEmpty()) {
                out.put(ScfyResultEnvelope.ERRORS, vr.errors());
            }
            addWarnings(out, vr.warnings());
            return out;
        }

        ScfyResponse resp;
        try {
            resp = client.get(ep, vr.normalized());
        } catch (Exception e) {
            log.warn("scfy 工具调用异常 endpoint={} params={}", endpointId, vr.normalized(), e);
            Map<String, Object> out = base(ep);
            out.put(ScfyResultEnvelope.OK, false);
            out.put(ScfyResultEnvelope.ERRORS, List.of("调用异常：" + e.getMessage()));
            return out;
        }

        Map<String, Object> out = base(ep);
        if (!resp.ok()) {
            out.put(ScfyResultEnvelope.OK, false);
            out.put(ScfyResultEnvelope.ERRORS, List.of(resp.reason()));
            out.put(ScfyResultEnvelope.HTTP_STATUS, resp.httpStatus());
            out.put(ScfyResultEnvelope.CODE, resp.code());
            addWarnings(out, vr.warnings());
            return out;
        }

        out.put(ScfyResultEnvelope.OK, true);
        Object data = toPlain(resp.data());
        out.put(ScfyResultEnvelope.DATA, trim(data, out));
        addWarnings(out, vr.warnings());
        out.put(ScfyResultEnvelope.ELAPSED_MS, resp.elapsedMs());
        if (resp.truncated()) {
            // 响应体被字节上限截断 —— 与「条目裁剪」是两件事，分别标注
            out.put(ScfyResultEnvelope.RESPONSE_TRUNCATED, true);
        }
        return out;
    }

    /**
     * 组装工具返回的公共字段。
     * <p>带上 {@code endpoint} 与 {@code note}：审计里能一眼看出「这条结论来自哪个接口」，
     * 以及该接口有没有「文档与实测不符」的历史。</p>
     */
    private Map<String, Object> base(ScfyEndpoint ep) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put(ScfyResultEnvelope.ENDPOINT, ep.id());
        out.put(ScfyResultEnvelope.SOURCE, "非遗四川 2023 / " + ep.fullPath());
        if (ep.hasDocMismatch()) {
            List<String> notes = new ArrayList<>();
            for (ScfyParam p : ep.params()) {
                if (p.docNote() != null && !p.docNote().isBlank()) {
                    notes.add(p.name() + "：" + p.docNote());
                }
            }
            out.put(ScfyResultEnvelope.DOC_MISMATCH, notes);
        }
        return out;
    }

    private void addWarnings(Map<String, Object> out, List<String> warnings) {
        if (warnings != null && !warnings.isEmpty()) {
            out.put(ScfyResultEnvelope.WARNINGS, warnings);
        }
    }

    /**
     * 条目裁剪：数组超过 MAX_ITEMS 时截断并标注真实总数。
     * <p>也处理「data 是对象、数组藏在某个字段里」的常见形状
     * （如 {@code {areasTopFewList:[...]}}、{@code {dataList:[...]}}）。</p>
     */
    @SuppressWarnings("unchecked")
    private Object trim(Object data, Map<String, Object> out) {
        if (data instanceof List<?> list) {
            if (list.size() > MAX_ITEMS) {
                out.put(ScfyResultEnvelope.TRUNCATED, true);
                out.put(ScfyResultEnvelope.TOTAL_ITEMS, list.size());
                out.put(ScfyResultEnvelope.RETURNED_ITEMS, MAX_ITEMS);
                return list.subList(0, MAX_ITEMS);
            }
            return list;
        }
        if (data instanceof Map<?, ?> map) {
            Map<String, Object> m = (Map<String, Object>) map;
            for (Map.Entry<String, Object> e : m.entrySet()) {
                if (e.getValue() instanceof List<?> l && l.size() > MAX_ITEMS) {
                    out.put(ScfyResultEnvelope.TRUNCATED, true);
                    out.put(ScfyResultEnvelope.TRUNCATED_FIELD, e.getKey());
                    out.put(ScfyResultEnvelope.TOTAL_ITEMS, l.size());
                    out.put(ScfyResultEnvelope.RETURNED_ITEMS, MAX_ITEMS);
                    m.put(e.getKey(), l.subList(0, MAX_ITEMS));
                }
            }
            return m;
        }
        return data;
    }

    /** JsonNode → 普通 Java 结构，便于工具层与审计层序列化，避免把 Jackson 类型泄漏出去。 */
    private static Object toPlain(JsonNode node) {
        if (node == null || node.isNull() || node.isMissingNode()) {
            return null;
        }
        return cn.aioa.integration.scfy.adapter.JsonNodes.toPlain(node);
    }
}
