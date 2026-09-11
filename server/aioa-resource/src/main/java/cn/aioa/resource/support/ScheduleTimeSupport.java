package cn.aioa.resource.support;

import cn.aioa.common.exception.BizException;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 数字员工执行时刻工具：解析 / 校验 / 归一 / 自然语言兜底解析。
 *
 * <p>统一的「HH:mm」存储格式；同时提供服务端自然语言兜底解析，
 * 避免前端解析失败时创建出无法调度的空配置数字员工。</p>
 */
public final class ScheduleTimeSupport {

    public static final DateTimeFormatter HH_MM = DateTimeFormatter.ofPattern("HH:mm");

    /** 中文数字 → 阿拉伯数字，用于「每天八点」这类表达 */
    private static final String[] CN_DIGITS = {"零", "一", "二", "三", "四", "五", "六", "七", "八", "九"};

    /** 形如「8:30」「08:30」「8点30」「8点30分」 */
    private static final Pattern P_HH_MM = Pattern.compile("(\\d{1,2})\\s*[:：点时]\\s*(\\d{1,2})?\\s*分?");
    /** 形如「8点」 */
    private static final Pattern P_HOUR = Pattern.compile("(\\d{1,2})\\s*[点时]");

    private ScheduleTimeSupport() {
    }

    /**
     * 解析用户输入的任意时间表达为 HH:mm。
     *
     * @param raw 原始输入，可为「08:00」「8:00」「8点」「早上8点」「晚上八点」「每天8点30分」等
     * @return HH:mm 格式；无法解析时返回 null（不抛异常，便于静默降级）
     */
    public static String parseFlexible(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        String s = normalizeCn(raw.trim());

        Integer hour = null;
        int minute = 0;

        // 先尝试带分钟的「N点M分 / N:M」
        Matcher mm = P_HH_MM.matcher(s);
        if (mm.find()) {
            hour = toInt(mm.group(1));
            Integer mi = toInt(mm.group(2));
            minute = mi == null ? 0 : mi;
        } else {
            // 再尝试整点「N点」
            Matcher mh = P_HOUR.matcher(s);
            if (mh.find()) {
                hour = toInt(mh.group(1));
            }
        }
        if (hour == null) {
            return null;
        }
        // 「半」表示 30 分（未显式给出分钟时生效）
        if (minute == 0 && s.matches(".*[点時时]\\s*半.*")) {
            minute = 30;
        }
        // 上午/下午/晚上等时段词修正（必须在取出数字之后统一处理，
        // 否则「晚上八点」会错误地返回 08:00）
        hour = applyPeriod(s, hour);
        return format(hour, minute);
    }

    /** 依据时段词修正小时：「下午/晚上」+12（12 点除外），「凌晨/早上/上午/半夜」12 点归零。 */
    private static int applyPeriod(String s, int hour) {
        boolean pm = s.matches(".*(下午|晚上|傍晚|晚间|夜里|夜间).*");
        boolean am = s.matches(".*(凌晨|早上|早晨|上午|半夜|深夜).*");
        if (pm && hour < 12) {
            return hour + 12;
        }
        if (am && hour == 12) {
            return 0;
        }
        return hour;
    }

    /**
     * 校验并归一执行时刻：合法返回 HH:mm，空返回 null；非法抛 400。
     */
    public static String normalize(String time) {
        if (time == null || time.isBlank()) {
            return null;
        }
        try {
            return LocalTime.parse(time.trim(), HH_MM).format(HH_MM);
        } catch (Exception e) {
            throw BizException.badRequest("执行时刻格式无效，应为 HH:mm（如 08:00）");
        }
    }

    /** 校验执行时刻（空放行，非法抛 400）。 */
    public static void validate(String time) {
        if (time == null || time.isBlank()) {
            return;
        }
        try {
            LocalTime.parse(time.trim(), HH_MM);
        } catch (Exception e) {
            throw BizException.badRequest("执行时刻格式无效，应为 HH:mm（如 08:00）");
        }
    }

    /**
     * 中文数字转阿拉伯数字。
     *
     * <p>顺序很关键：先处理「十X」复合（十一点 → 11点），再处理个位「X点」。
     * 若反过来，个位规则会把「十一点」中的「一点」先替换成「十1点」，得到错误结果。
     * 「点/时」先统一替换为占位符，最后由占位符还原，避免各规则互相干扰。</p>
     */
    private static String normalizeCn(String s) {
        String out = s;
        // 「十一点」→ 11；「十二点」→ 12；「十点」→ 10
        out = out.replaceAll("十([一二两三四五六七八九])[点时]", "$1PLACEHOLDER");
        out = out.replaceAll("十[点时]", "10PLACEHOLDER");
        // 「八点」→ 8（此时「十X点」已被占位符保护，不会再被误匹配）
        for (int i = 0; i < CN_DIGITS.length; i++) {
            out = out.replace(CN_DIGITS[i] + "点", i + "PLACEHOLDER");
            out = out.replace(CN_DIGITS[i] + "时", i + "PLACEHOLDER");
        }
        // 「十X」的 X 换算为两位数结果
        out = out.replaceAll("([一二两三四五六七八九])PLACEHOLDER", "1$1PLACEHOLDER");
        Matcher m = Pattern.compile("([零一二两三四五六七八九])PLACEHOLDER").matcher(out);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            int d = cnToInt(m.group(1));
            m.appendReplacement(sb, (d < 0 ? m.group(1) : String.valueOf(d)) + "点");
        }
        m.appendTail(sb);
        out = sb.toString();
        out = out.replace("10PLACEHOLDER", "10点");
        // 全角冒号统一
        out = out.replace("：", ":");
        return out;
    }

    /** 中文个位数字 → 整数，无法识别返回 -1。 */
    private static int cnToInt(String c) {
        for (int i = 0; i < CN_DIGITS.length; i++) {
            if (CN_DIGITS[i].equals(c)) {
                return i;
            }
        }
        if ("两".equals(c)) {
            return 2;
        }
        return -1;
    }

    private static Integer toInt(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(s.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String format(int hour, int minute) {
        if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
            return null;
        }
        return String.format("%02d:%02d", hour, minute);
    }
}
