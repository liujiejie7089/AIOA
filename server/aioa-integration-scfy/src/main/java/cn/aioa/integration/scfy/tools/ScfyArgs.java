package cn.aioa.integration.scfy.tools;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 工具入参装配。
 *
 * <p>{@link #of(Object...)} 会<b>丢弃 null 值</b> —— 这一点是有意的：
 * 「参数没传」与「参数传了 null」在 scfy 那里必须表现一致，
 * 否则 URL 里会出现 {@code &area=} 这样的空值参数，而后端对空值的处理是
 * 「按空字符串过滤」而不是「不筛选」，会静默返回错误结果。</p>
 */
public final class ScfyArgs {

    private ScfyArgs() {
    }

    /** 用法：{@code ScfyArgs.of("area", area, "pageSize", pageSize)} —— 奇数个参数抛异常。 */
    public static Map<String, Object> of(Object... kv) {
        if (kv.length % 2 != 0) {
            throw new IllegalArgumentException("参数必须成对出现（名, 值）");
        }
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            Object v = kv[i + 1];
            if (v != null) {
                m.put(String.valueOf(kv[i]), v);
            }
        }
        return m;
    }
}
