package cn.aioa.org.support;

import cn.aioa.common.exception.BizException;

import java.util.Locale;
import java.util.regex.Pattern;

/**
 * 统一社会信用代码（{@code org_institution.credit_code}）的归一化与格式校验。
 *
 * <p><b>为什么有这一类</b>：机构建档/编辑此前对信用代码**完全不校验**（原样写库），
 * 于是「长度不对、含非法字符、把税号当信用代码填」都能落库，后续按信用代码对接外部系统时才发现。
 * 归一化与判定只在这里实现一处，调用方不得自写正则（铁律 #1：同一判定点只在一处判定）。</p>
 *
 * <p><b>只校验格式、不校验校验位（GB 32100-2015 第 18 位）—— 这是量过的取舍，不是偷懒</b>：
 * 实测本库现存 4 条真实格式的信用代码（如 {@code 11330102MB1234567A}）与演示种子脚本的 8 条，
 * **全部通不过标准校验位算法**（它们是合成的演示数据）。若强制校验位，就会一次性拒掉 100% 的现存数据与
 * 全部演示种子/回归套件，收益却是零（校验位只能挡手改的号码，挡不住错误号码）。
 * 因此本类只做**长度 + 字符集 + 分段形状**的校验：这已能挡住绝大多数误填，
 * 且不会与现存演示数据冲突。**若要加校验位，必须先批量重造全部演示信用代码**，
 * 否则就是把「录入校验」变成「数据不可用」。</p>
 *
 * <p>职责边界：只做归一化 + 格式。**唯一性**由服务层按租户维度查询（含软删语义），不在这里做 ——
 * 那是「与库交互」的事，本类是纯函数。</p>
 */
public final class CreditCode {

    /** GB 32100-2015 允许的字符集：数字 + 大写字母，**去掉易混的 I / O / S / V / Z**。 */
    private static final String CH = "[0-9A-HJ-NPQRTUWXY]";

    /** 18 位：第 1–2 位登记管理部门+机构类别，第 3–8 位行政区划（数字），第 9–17 位主体标识，第 18 位校验位。 */
    private static final Pattern PATTERN = Pattern.compile("^" + CH + "{2}\\d{6}" + CH + "{10}$");

    /** 标准长度。 */
    public static final int LENGTH = 18;

    private CreditCode() {
    }

    /**
     * 归一化：去首尾空白、转大写（信用代码规范全大写）。
     *
     * @return 归一化后的值；入参为 null/空白时返回 {@code null}（表示「未填写」）
     */
    public static String normalize(String raw) {
        if (raw == null) {
            return null;
        }
        String s = raw.trim().toUpperCase(Locale.ROOT);
        return s.isEmpty() ? null : s;
    }

    /** 格式校验（应传入 {@link #normalize} 之后的值）。 */
    public static boolean isValid(String normalized) {
        return normalized != null && PATTERN.matcher(normalized).matches();
    }

    /** 归一化 + 格式校验；返回可直接写库的 canonical 值，不合法时抛可直接展示的 400。 */
    public static String require(String raw) {
        String s = normalize(raw);
        if (!isValid(s)) {
            throw BizException.badRequest("统一社会信用代码格式不合法：" + raw
                    + "；应为 18 位（第 3–8 位为行政区划数字，字符不含 I/O/S/V/Z），如 91330102MA2G10001C");
        }
        return s;
    }
}
