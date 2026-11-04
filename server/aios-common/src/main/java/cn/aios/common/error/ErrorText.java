package cn.aios.common.error;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 错误文案清洗器：把「开发看得懂、用户看不懂」的原始信息转成可展示的一句话。
 *
 * <p>为什么需要它：异常消息里天然带着内部细节 ——
 * {@code java.lang.Long}、{@code com.mysql.cj.jdbc.exceptions...}、
 * {@code select ... from sys_user}、{@code C:\aios\server\...}、
 * {@code sk-abcdef123456}。这些一旦被塞进 {@code message} 直接展示，
 * 既是**信息泄漏**（表名、路径、密钥片段），也是**体验灾难**（用户不知道该怎么办）。
 * 原始信息不是不记，而是<b>只进日志</b>（见 GlobalExceptionHandler）。</p>
 *
 * <p>清洗是「兜底」而不是「主力」：抛错方应当直接给出人话；
 * 只有在必须透传上游/框架消息时才走这里。</p>
 */
public final class ErrorText {

    private static final int MAX_LEN = 200;

    /** 全限定类名：com.foo.Bar / java.lang.Long / cn.aios.xxx.Yyy。 */
    private static final Pattern FQCN =
            Pattern.compile("\\b(?:[a-zA-Z_][\\w$]*\\.){2,}[A-Za-z_$][\\w$]*\\b");

    /** 堆栈行：at com.foo.Bar.baz(Bar.java:12)。 */
    private static final Pattern STACK_LINE = Pattern.compile("(?m)^\\s*at\\s+\\S+.*$");

    /** SQL 片段（含参数占位与表名）。 */
    private static final Pattern SQL = Pattern.compile(
            "(?is)\\b(select|insert\\s+into|update\\s+\\w+\\s+set|delete\\s+from|create\\s+table|alter\\s+table|drop\\s+table)\\b.{0,180}");

    /** 数据库驱动/约束类异常的关键字。 */
    private static final Pattern DB_NOISE = Pattern.compile(
            "(?is)(sqlexception|sqlsyntaxerror|dataIntegrityViolation|Duplicate entry|"
                    + "constraint|deadlock|Lock wait timeout|Communications link failure|"
                    + "Unknown column|Table '.*' doesn't exist)");

    /** 绝对路径：C:\x\y、/opt/app/x、file:/... 。 */
    private static final Pattern FILE_PATH = Pattern.compile(
            "(?:(?:[A-Za-z]:\\\\|/)[\\w.\\-]+){2,}[\\\\/]?[\\w.\\-]*");

    /** 密钥/令牌形态：sk-xxx、Bearer xxx、password=xxx。 */
    private static final Pattern SECRET = Pattern.compile(
            "(?i)\\b(sk-[A-Za-z0-9_\\-]{6,}|Bearer\\s+[A-Za-z0-9._\\-]{8,}|"
                    + "(?:password|passwd|pwd|api[_-]?key|secret|token)\\s*[=:]\\s*[^\\s,;\"'}]{3,})");

    /** Jackson / Servlet 的模板化噪音，整段删掉后句子仍成立。 */
    private static final Pattern FRAMEWORK_NOISE = Pattern.compile(
            "(?i)(JSON parse error:\\s*|Could not read document:\\s*|"
                    + "Failed to convert value of type\\s*'?[\\w.$]+'?\\s*to required type\\s*'?[\\w.$]+'?;?\\s*|"
                    + "nested exception is\\s*|Servlet\\.service\\(\\)\\s*for servlet\\s*\\[?\\w*]?\\s*|"
                    + "org\\.springframework[\\w.]*:\\s*)");

    private ErrorText() {
    }

    /**
     * 清洗为可展示文案；清洗后为空则返回 {@code fallback}。
     *
     * @param raw      原始异常/上游消息，可为 null
     * @param fallback 清洗后为空时的兜底文案（通常取 ErrorCode.defaultMessage()）
     */
    public static String sanitize(String raw, String fallback) {
        if (raw == null || raw.isBlank()) {
            return fallback;
        }
        String s = raw;
        s = STACK_LINE.matcher(s).replaceAll(" ");
        s = maskSecrets(s);
        // 数据库噪音整句下沉为一句人话：表名/约束名对用户毫无意义
        if (DB_NOISE.matcher(s).find() || SQL.matcher(s).find()) {
            return "数据处理时发生冲突或失败，本次操作没有完成".equals(fallback)
                    ? fallback : "数据处理失败（可能是重复提交或数据已被修改）";
        }
        s = FRAMEWORK_NOISE.matcher(s).replaceAll("");
        s = SQL.matcher(s).replaceAll(" ");
        s = FQCN.matcher(s).replaceAll("");
        s = FILE_PATH.matcher(s).replaceAll("");
        s = s.replaceAll("\\s{2,}", " ").trim();
        // 去掉首尾的冒号/分号/引号残渣
        s = s.replaceAll("^[\\s:;，,、]+", "").replaceAll("[\\s:;，,、]+$", "");
        if (s.isBlank()) {
            return fallback;
        }
        if (s.length() > MAX_LEN) {
            s = s.substring(0, MAX_LEN) + "…";
        }
        return s;
    }

    /** 只做脱敏（日志里也要用：日志可以留结构，但密钥不该落盘）。 */
    public static String maskSecrets(String raw) {
        if (raw == null) {
            return null;
        }
        return SECRET.matcher(raw).replaceAll(m -> {
            String hit = m.group();
            int keep = Math.min(4, Math.max(0, hit.length() / 6));
            return hit.length() <= keep + 3 ? "***" : hit.substring(0, keep) + "***";
        });
    }

    /**
     * 从 Spring 绑定异常里抽出「字段 → 一句人话」。
     *
     * <p>默认消息是英文（{@code must not be blank}），直接甩给用户等于没提示；
     * 这里做一层最小可用的中文化，未覆盖的仍走清洗后的原文。</p>
     */
    public static String fieldMessage(String defaultMessage) {
        if (defaultMessage == null || defaultMessage.isBlank()) {
            return "填写不正确";
        }
        String m = defaultMessage.trim();
        String lower = m.toLowerCase();
        if (lower.contains("must not be blank") || lower.contains("must not be empty")
                || lower.contains("must not be null") || lower.contains("不能为空")) {
            return "不能为空";
        }
        if (lower.contains("size must be between") || lower.contains("length must be between")) {
            return "长度超出允许范围";
        }
        if (lower.contains("must be true") || lower.contains("must be false")) {
            return "取值不符合要求";
        }
        if (lower.contains("must be greater than") || lower.contains("must be less than")
                || lower.contains("must be between")) {
            return "数值超出允许范围";
        }
        if (lower.contains("must match") || lower.contains("格式")) {
            return "格式不正确";
        }
        if (lower.contains("failed to convert") || lower.contains("type mismatch")) {
            return "类型不正确";
        }
        return sanitize(m, "填写不正确");
    }

    /** 把字段错误按「字段名 → 提示」压平成可序列化结构，同字段多条只留第一条。 */
    public static List<FieldError> flatten(List<FieldError> raw) {
        if (raw == null || raw.isEmpty()) {
            return List.of();
        }
        List<FieldError> out = new ArrayList<>();
        for (FieldError f : raw) {
            boolean dup = out.stream().anyMatch(o -> o.field().equals(f.field()));
            if (!dup) {
                out.add(f);
            }
        }
        return out;
    }

    /** 字段级错误：前端据此标红具体输入框。 */
    public record FieldError(String field, String message) {
    }
}
