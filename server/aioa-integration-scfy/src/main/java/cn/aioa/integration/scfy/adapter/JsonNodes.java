package cn.aioa.integration.scfy.adapter;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * JsonNode → 普通 Java 结构。
 *
 * <p>存在的意义是把 Jackson 类型<b>挡在适配器边界内</b>：
 * 工具层、审计层只需要 Map/List/String/Number，强行传 JsonNode 过去会让
 * 「怎么读这个节点」的写法扩散到全项目，且序列化时出现 Jackson 特有的形状差异。</p>
 */
public final class JsonNodes {

    private JsonNodes() {
    }

    public static Object toPlain(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return null;
        }
        if (n.isObject()) {
            Map<String, Object> m = new LinkedHashMap<>();
            n.fields().forEachRemaining(e -> m.put(e.getKey(), toPlain(e.getValue())));
            return m;
        }
        if (n.isArray()) {
            List<Object> l = new ArrayList<>();
            n.forEach(x -> l.add(toPlain(x)));
            return l;
        }
        if (n.isTextual()) {
            return n.asText();
        }
        if (n.isBoolean()) {
            return n.asBoolean();
        }
        if (n.isIntegralNumber()) {
            // 统一成长整型，避免 int/long 在 JSON 序列化时表现不一致
            return n.asLong();
        }
        if (n.isFloatingPointNumber()) {
            return n.asDouble();
        }
        if (n.isNumber()) {
            return n.numberValue();
        }
        return n.asText();
    }
}
