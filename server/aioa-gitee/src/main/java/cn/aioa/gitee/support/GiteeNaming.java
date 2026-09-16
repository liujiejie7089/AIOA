package cn.aioa.gitee.support;

import java.text.Normalizer;
import java.util.Locale;

/**
 * Gitee 仓库命名规则。
 *
 * <p><b>为什么需要它</b>：Gitee 的仓库 path 只接受 {@code [A-Za-z0-9._-]}，而平台的项目名
 * 极可能是中文（「政务数据中台」）。若不处理，用户第一次建项目就会拿到
 * 「path is invalid」这种与他的输入看起来毫不相关的报错。</p>
 *
 * <p><b>退化策略</b>：中文（或纯符号）名字清洗后可能为空。此时不使用「随机名」
 * ——随机名会让同一个人重试两次得到两个不同的仓库，无法排障。
 * 改为对原名取**确定性短哈希**（{@code proj-<6 位>}），于是同一个项目名
 * 永远得到同一个仓库名，可重复且可追溯。</p>
 */
public final class GiteeNaming {

    /** 部门命名空间前缀：部门隔离在仓库名上可观测。 */
    public static String namespaceOf(Long departmentId) {
        return "dept" + (departmentId == null ? "0" : departmentId) + "-";
    }

    /**
     * 生成合法的仓库 path。
     *
     * @param raw      原始名称（可为中文）
     * @param maxLength 长度上限（含命名空间前缀）
     * @param prefix   命名空间前缀（可为空）
     */
    public static String repoPath(String raw, int maxLength, String prefix) {
        String p = prefix == null ? "" : prefix;
        String body = sanitize(raw);
        if (body.isEmpty()) {
            body = "proj-" + shortHash(raw);
        }
        // 仓库 path 不能以符号开头（Gitee 会拒），前缀本身以字母开头故安全
        int room = Math.max(8, maxLength - p.length());
        if (body.length() > room) {
            body = body.substring(0, room);
        }
        String out = p + body;
        // 收尾去掉可能的连字符/点，避免 "xxx-" 这类被判非法
        while (!out.isEmpty() && "-._".indexOf(out.charAt(out.length() - 1)) >= 0) {
            out = out.substring(0, out.length() - 1);
        }
        return out.isEmpty() ? p + "proj-" + shortHash(raw) : out;
    }

    /** 清洗为 Gitee 可接受的字符集；非 ASCII 字符会被 Normalizer 尽量还原。 */
    static String sanitize(String raw) {
        if (raw == null) {
            return "";
        }
        // 先做兼容分解，能还原的带音标拉丁字母尽量还原（如 café → cafe）
        String s = Normalizer.normalize(raw, Normalizer.Form.NFKD)
                .replaceAll("\\p{M}+", "")
                .toLowerCase(Locale.ROOT);
        StringBuilder sb = new StringBuilder();
        for (char c : s.toCharArray()) {
            if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.') {
                sb.append(c);
            } else if (sb.length() > 0 && sb.charAt(sb.length() - 1) != '-') {
                sb.append('-');
            }
        }
        String out = sb.toString();
        while (out.startsWith("-") || out.startsWith(".")) {
            out = out.substring(1);
        }
        while (out.endsWith("-") || out.endsWith(".")) {
            out = out.substring(0, out.length() - 1);
        }
        return out;
    }

    /** 确定性短哈希（同名同值），用于中文名的退化命名。 */
    static String shortHash(String raw) {
        int h = 0;
        for (char c : (raw == null ? "" : raw).toCharArray()) {
            h = 31 * h + c;
        }
        String hex = Integer.toHexString(h & 0x7fffffff);
        StringBuilder sb = new StringBuilder(hex);
        while (sb.length() < 6) {
            sb.insert(0, '0');
        }
        return sb.substring(sb.length() - 6);
    }

    private GiteeNaming() {
    }
}
