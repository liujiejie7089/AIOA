package cn.aioa.org.support;

import cn.aioa.common.exception.BizException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

/** 请求体取值与校验小工具（避免各服务重复判空/转型）。 */
public final class Vals {

    private Vals() {
    }

    public static long lng(Map<String, Object> body, String key, long def) {
        Object v = body == null ? null : body.get(key);
        if (v == null) {
            return def;
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    public static long lng(Map<String, Object> body, String key) {
        return lng(body, key, 0L);
    }

    public static Long lngObj(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        if (v == null || String.valueOf(v).isBlank()) {
            return null;
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public static int integer(Map<String, Object> body, String key, int def) {
        Object v = body == null ? null : body.get(key);
        if (v == null) {
            return def;
        }
        if (v instanceof Number n) {
            return n.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    public static String str(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        if (v == null) {
            return null;
        }
        String s = String.valueOf(v).trim();
        return s.isEmpty() ? null : s;
    }

    public static String str(Map<String, Object> body, String key, String def) {
        String s = str(body, key);
        return s == null ? def : s;
    }

    public static String require(Map<String, Object> body, String key, String label) {
        String s = str(body, key);
        if (s == null) {
            throw BizException.badRequest(label + "不能为空");
        }
        return s;
    }

    public static boolean bool(Map<String, Object> body, String key, boolean def) {
        Object v = body == null ? null : body.get(key);
        if (v == null) {
            return def;
        }
        if (v instanceof Boolean b) {
            return b;
        }
        String s = String.valueOf(v).trim().toLowerCase();
        if ("true".equals(s) || "1".equals(s) || "yes".equals(s)) {
            return true;
        }
        if ("false".equals(s) || "0".equals(s) || "no".equals(s)) {
            return false;
        }
        return def;
    }

    public static BigDecimal dec(Map<String, Object> body, String key, BigDecimal def) {
        Object v = body == null ? null : body.get(key);
        if (v == null || String.valueOf(v).isBlank()) {
            return def;
        }
        try {
            return new BigDecimal(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    public static LocalDate date(Map<String, Object> body, String key) {
        String s = str(body, key);
        if (s == null) {
            return null;
        }
        return LocalDate.parse(normalizeDate(s));
    }

    /** 关键字模糊查询条件值：%kw%。 */
    public static String like(String kw) {
        return kw == null || kw.isBlank() ? null : "%" + kw.trim() + "%";
    }

    @SuppressWarnings("unchecked")
    public static List<Map<String, Object>> list(Map<String, Object> body, String key) {
        Object v = body == null ? null : body.get(key);
        if (v instanceof List<?> l) {
            return (List<Map<String, Object>>) l;
        }
        return List.of();
    }

    /** 当前周期 YYYY-MM。 */
    public static String nowPeriod() {
        return LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy-MM"));
    }

    private static String normalizeDate(String s) {
        String t = s.replace('/', '-');
        if (t.length() == 7) {
            t = t + "-01";
        }
        if (t.length() == 10 && t.charAt(7) == '-') {
            // yyyy-M-d 补齐
            String[] parts = t.split("-");
            if (parts.length == 3) {
                return String.format("%s-%02d-%02d", parts[0],
                        Integer.parseInt(parts[1]), Integer.parseInt(parts[2]));
            }
        }
        return t;
    }
}
