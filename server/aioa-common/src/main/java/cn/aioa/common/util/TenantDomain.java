package cn.aioa.common.util;

import java.util.regex.Pattern;

/**
 * 租户登录域名（V66 / docs/38）。
 *
 * <p><b>为什么放在 aioa-common 且只有这一个类</b>：域名的归一化与格式校验同时被
 * 「平台建租户 / 改租户」（{@code aioa-admin}）与「租户建子租户 / 改子租户」（{@code aioa-org}）使用，
 * 而这两个模块彼此没有依赖，只共同依赖 {@code aioa-common}。
 * 若两边各写一份正则，迟早会出现「平台不接受、租户端接受」的同一个域名 ——
 * 这正是本项目反复出现的「同一判定点两处实现」缺陷形态。</p>
 *
 * <p>职责边界：只做<b>归一化 + 格式校验</b>。**不做 DNS 解析、证书绑定、可用性探测** ——
 * 本项目是本地单端口部署，真域名解析不在代码范围内（docs/38 §3 假设 4）。</p>
 */
public final class TenantDomain {

    /** 单个 label：字母数字开头结尾，中间可含连字符；禁止下划线、中文、空格。 */
    private static final String LABEL = "[a-z0-9]([a-z0-9-]*[a-z0-9])?";

    /** 至少两段（必须有点），整体小写。 */
    private static final Pattern PATTERN =
            Pattern.compile("^" + LABEL + "(\\." + LABEL + ")+$");

    private static final int MAX_LENGTH = 128;
    private static final int MAX_LABEL_LENGTH = 63;

    private TenantDomain() {
    }

    /**
     * 归一化：去首尾空白、转小写、去掉结尾的单个点（用户从浏览器地址栏复制时常见）。
     *
     * @return 归一化后的域名；入参为 null/空白时返回 {@code null}（表示「未分配域名」）
     */
    public static String normalize(String raw) {
        if (raw == null) {
            return null;
        }
        String s = raw.trim().toLowerCase();
        if (s.endsWith(".")) {
            s = s.substring(0, s.length() - 1);
        }
        return s.isEmpty() ? null : s;
    }

    /** 格式校验（应传入 {@link #normalize} 之后的值）。 */
    public static boolean isValid(String normalized) {
        if (normalized == null || normalized.isEmpty() || normalized.length() > MAX_LENGTH) {
            return false;
        }
        if (!PATTERN.matcher(normalized).matches()) {
            return false;
        }
        for (String label : normalized.split("\\.")) {
            if (label.length() > MAX_LABEL_LENGTH) {
                return false;
            }
        }
        return true;
    }

    /** 归一化 + 校验；不合法时抛出可直接展示给用户的错误文案。 */
    public static String require(String raw) {
        String s = normalize(raw);
        if (s == null) {
            throw cn.aioa.common.exception.BizException.badRequest("登录域名不能为空");
        }
        if (!isValid(s)) {
            throw cn.aioa.common.exception.BizException.badRequest(
                    "登录域名格式不合法（应为小写字母/数字/连字符组成的多级域名，如 dsj.aioa.local）：" + raw);
        }
        return s;
    }
}
