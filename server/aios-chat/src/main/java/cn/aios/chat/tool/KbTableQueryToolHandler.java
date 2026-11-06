package cn.aios.chat.tool;

import cn.aios.resource.service.KbTableQueryService;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 「知识库表格聚合」工具（2026-11-06，docs/74 P0-2）。
 *
 * <p>解决的问题：用户上传的是名录 / 台账类 Excel（1241 行），却问「共有多少个」「按地区分别多少」。
 * 检索只能给出 topK 个片段（默认 5），<b>拿 5 行明细回答总数是结构性不可能</b>——
 * 模型此前只能回「知识库暂未收录」，看起来像库是空的。</p>
 *
 * <p>本工具直接对表格行做 count / group by，结果是**确定的数字**而不是模型的推测。
 * 工具名刻意避开 {@code search_kb_documents}：语义不同（一个是检索原文，一个是算数）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class KbTableQueryToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "kb_table_query";

    private final KbTableQueryService kbTableQueryService;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "对知识库里的表格类资料（Excel 名录 / 台账 / 清单 / 成绩单）做聚合统计与**逐行取数**："
                + "总条数、按某列分组计数、按条件筛选、分页取出命中行。"
                + "当用户问「一共有多少个」「各省分别多少」「按批次统计」这类**计数/分组**问题时必须调用；"
                + "当用户要「列出全部 / 所有 / 逐条」明细时，也用它并配合 offset 翻页取全"
                + "（返回里的 hasMore=true 就说明还有下一页，必须继续取，不要只答第一页）。"
                + "不传 groupBy 时只返回总条数与命中行。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"docName\":{\"type\":\"string\",\"description\":\"资料名，可只给片段，"
                + "如「省级非遗项目名录」「成绩单」\"},"
                + "\"docId\":{\"type\":\"integer\",\"description\":\"资料 id，已知时优先于 docName\"},"
                + "\"sheet\":{\"type\":\"string\",\"description\":\"表名，如「成绩明细」「成绩汇总」；"
                + "一份资料有多张表时用它指定（不传则自动选命中行最多的那张）\"},"
                + "\"groupBy\":{\"type\":\"string\",\"description\":\"分组列名，如「申报地区或单位」「课程性质」；"
                + "不传则只返回总条数与命中行\"},"
                + "\"filter\":{\"type\":\"string\",\"description\":\"筛选条件，形如「批次=第六批」，"
                + "值为包含匹配；可省略\"},"
                + "\"valueLimit\":{\"type\":\"integer\",\"description\":\"分组结果最多返回几项，默认 20，上限 50\"},"
                + "\"offset\":{\"type\":\"integer\",\"description\":\"命中行起始下标，翻页用；默认 0\"},"
                + "\"limit\":{\"type\":\"integer\",\"description\":\"本页返回多少行，默认 50，上限 500；"
                + "要列全部明细时给大值或按 nextOffset 翻页\"}"
                + "},\"required\":[\"docName\"]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            String docName = str(args, "docName");
            Long docId = longArg(args, "docId");
            String groupBy = str(args, "groupBy");
            String filter = str(args, "filter");
            Integer valueLimit = intArg(args, "valueLimit");
            Integer offset = intArg(args, "offset");
            Integer rowLimit = intArg(args, "limit");
            String sheet = str(args, "sheet");
            return kbTableQueryService.query(user.getTenantId(), user.getUserId(),
                    docName, docId, groupBy, filter, valueLimit, offset, rowLimit, sheet);
        } catch (Exception e) {
            // 与网关约定一致：业务失败不抛异常，返回 {ok:false} 交模型组织回答
            log.warn("kb_table_query failed: {}", e.getMessage());
            return Map.of("ok", false, "error", String.valueOf(e.getMessage()));
        }
    }

    private static String str(Map<String, Object> args, String key) {
        Object v = args == null ? null : args.get(key);
        if (v == null) {
            return null;
        }
        String s = String.valueOf(v).trim();
        return s.isEmpty() || "null".equalsIgnoreCase(s) ? null : s;
    }

    private static Long longArg(Map<String, Object> args, String key) {
        String s = str(args, key);
        if (s == null) {
            return null;
        }
        try {
            return Long.parseLong(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Integer intArg(Map<String, Object> args, String key) {
        String s = str(args, key);
        if (s == null) {
            return null;
        }
        try {
            return Integer.parseInt(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
