package cn.aioa.resource.model;

import lombok.Data;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 专家运行期配置的最终形态（各层级 merge 后的结果）。
 *
 * <p>字段为 null 表示该层未配置、继续沿用更低优先级层的值；
 * 解析完成后所有字段都会被默认值兜底，不会为 null（见 ExpertConfigService.defaults）。</p>
 */
@Data
public class ExpertSettings {

    /** 专家开关：关闭后不可见且调用被拒。 */
    private Boolean enabled;

    /** 可见范围：ALL / TENANT / INSTITUTION / DEPT / USER。 */
    private String visibleScope;

    /**
     * 可见范围的<b>目标清单</b>（V65）：机构 id / 部门 id / 用户 id，含义随 {@link #visibleScope} 而定。
     *
     * <p>此前只有 {@code visibleScope} 一个字符串，服务端判定退化为「当前用户有没有该维度归属」
     * —— 选「指定机构」与选「本机构」在行为上完全一样，`visibleScope=INSTITUTION` 的语义
     * 实际是「凡有机构归属的人都可见」。也就是说，这个可配置项<b>配了等于没配</b>。</p>
     *
     * <p>语义定稿：{@code INSTITUTION / DEPT / USER} 三档<b>以清单为准</b>，
     * 清单为空 ⇒ 明确「不对任何人可见」，而不是退回「全员可见」
     * （空集合退化成全员可见，正是「配了等于没配」的成因）。
     * {@code ALL} 忽略清单；{@code TENANT} 允许用清单收窄到指定租户，留空即本租户全员。</p>
     */
    private List<Long> visibleTargets;

    /** 新用户进入时是否默认挂载。 */
    private Boolean defaultEnabled;

    /** 知识库范围：ALL 或逗号分隔的文档 ID（如 "12,13"）。 */
    private String kbScope;

    /** 模型标识，透传给 agent 的 model_ref。 */
    private String model;

    /** 采样温度 0.0–1.0。 */
    private Double temperature;

    /** 召回条数 1–20。 */
    private Integer topK;

    /** 相似度阈值 0.0–1.0，低于该分的切片被丢弃。 */
    private Double threshold;

    /** 检索模式：vector / bm25 / hybrid。 */
    private String retrievalMode;

    /** 工具开关：键为工具名（sql_query / python_script / kb_search）。 */
    private Map<String, Boolean> tools;

    /** 展示排序，小的在前。 */
    private Integer sort;

    /** 切分块大小（入库时使用）。 */
    private Integer chunkSize;

    /** 切分重叠（入库时使用）。 */
    private Integer chunkOverlap;

    /** 系统提示词（专家角色设定与职责边界）。 */
    private String systemPrompt;

    /** 知识范围描述（检索范围/领域边界的文字说明）。 */
    private String knowledgeScope;

    /** 允许的检索模式常量。 */
    public static final String MODE_VECTOR = "vector";
    public static final String MODE_BM25 = "bm25";
    public static final String MODE_HYBRID = "hybrid";

    /**
     * 把「部分配置」合并到当前对象上：仅覆盖非 null 的键，并记录每个键的来源层级。
     *
     * @param partial 某一层的配置片段（Map，值为 JSON 基本类型）
     * @param layer   该层的名称（GLOBAL/TENANT/.../USER 或带作用域后缀）
     * @param sources 来源登记表，会被就地写入「键 -> 层级」
     * @return 实际被覆盖的键数量
     */
    public int mergeFrom(Map<String, Object> partial, String layer, Map<String, String> sources) {
        if (partial == null || partial.isEmpty()) {
            return 0;
        }
        int n = 0;
        for (Map.Entry<String, Object> e : partial.entrySet()) {
            Object v = e.getValue();
            if (v == null) {
                continue;
            }
            switch (e.getKey()) {
                case "enabled" -> this.enabled = Boolean.parseBoolean(String.valueOf(v));
                case "visibleScope" -> this.visibleScope = String.valueOf(v);
                case "visibleTargets" -> this.visibleTargets = toLongList(v);
                case "defaultEnabled" -> this.defaultEnabled = Boolean.parseBoolean(String.valueOf(v));
                case "kbScope" -> this.kbScope = String.valueOf(v);
                case "model" -> this.model = String.valueOf(v);
                case "temperature" -> this.temperature = Double.parseDouble(String.valueOf(v));
                case "topK" -> this.topK = Integer.parseInt(String.valueOf(v));
                case "threshold" -> this.threshold = Double.parseDouble(String.valueOf(v));
                case "retrievalMode" -> this.retrievalMode = String.valueOf(v);
                case "sort" -> this.sort = Integer.parseInt(String.valueOf(v));
                case "chunkSize" -> this.chunkSize = Integer.parseInt(String.valueOf(v));
                case "chunkOverlap" -> this.chunkOverlap = Integer.parseInt(String.valueOf(v));
                case "systemPrompt" -> this.systemPrompt = String.valueOf(v);
                case "knowledgeScope" -> this.knowledgeScope = String.valueOf(v);
                case "tools" -> {
                    Map<String, Boolean> merged = this.tools == null
                            ? new LinkedHashMap<>() : new LinkedHashMap<>(this.tools);
                    if (v instanceof Map<?, ?> m) {
                        m.forEach((k, val) -> merged.put(String.valueOf(k), Boolean.parseBoolean(String.valueOf(val))));
                    }
                    this.tools = merged;
                }
                default -> {
                    continue; // 未知键忽略，保证向后兼容（旧配置不会让新版本报错）
                }
            }
            sources.put(e.getKey(), layer);
            n++;
        }
        return n;
    }

    /**
     * 「可见范围」判定 —— <b>全系统唯一判定点</b>（铁律 #1）。
     *
     * <p>此前这段逻辑只存在于管理端专家列表（`ExpertConfigController` 的私有 `visible()`），
     * 而用户端目录（`CatalogService#availableExperts`）压根不看 `visibleScope`
     * ⇒ 管理端把专家配成「仅 A 机构可见」，H5 里 B 机构的成员照旧能看见并使用。
     * 同一个「谁能看见这位专家」被分在两处判定，且其中一处根本没判。
     * 现在两个入口都调本方法，配出来的范围才真的在用户端生效。</p>
     *
     * <p>语义定稿：</p>
     * <ul>
     *   <li>{@code ALL} / 空：全员可见（忽略清单）；</li>
     *   <li>{@code TENANT}：清单为空 ⇒ 本租户全员；非空 ⇒ 只对清单内的租户开放；</li>
     *   <li>{@code INSTITUTION / DEPT / USER}：只对清单内的机构 / 部门 / 用户开放，
     *       <b>清单为空 ⇒ 明确「不对任何人可见」</b> —— 空集合若退化成「全员可见」，
     *       就回到了「配了等于没配」的老路；</li>
     *   <li>未知值：<b>不放行</b>（而不是默认放行），避免拼错枚举把专家意外公开。</li>
     * </ul>
     *
     * <p><b>不含「管理员始终可见」的豁免</b>：那是调用方的策略（管理端必须让管理员看得到，
     * 否则把范围配窄后管理员自己就进不去配置页）。调用方负责在调本方法前放行管理员。</p>
     */
    public boolean visibleTo(cn.aioa.security.AuthUser user) {
        String scope = this.visibleScope;
        if (scope == null || scope.isBlank() || "ALL".equalsIgnoreCase(scope)) {
            return true;
        }
        List<Long> t = this.visibleTargets == null ? List.of() : this.visibleTargets;
        Long tenantId = user == null ? null : user.getTenantId();
        long tid = tenantId == null ? 0L : tenantId;
        switch (scope.toUpperCase()) {
            case "TENANT":
                return t.isEmpty() ? tid > 0 : t.contains(tid);
            case "INSTITUTION":
                return user != null && user.getInstitutionId() != null
                        && t.contains(user.getInstitutionId());
            case "DEPT":
                return user != null && user.getDepartmentId() != null
                        && t.contains(user.getDepartmentId());
            case "USER":
                return user != null && user.getUserId() != null
                        && t.contains(user.getUserId());
            default:
                return false;
        }
    }

    /** 工具是否启用：未登记的工具默认启用（保证新增工具不会因缺配置而不可用）。 */
    public boolean toolEnabled(String name) {
        if (tools == null || !tools.containsKey(name)) {
            return true;
        }
        Boolean v = tools.get(name);
        return v == null || v;
    }

    /**
     * 目标清单归一化：既接 JSON 数组（{@code [1,2]}），也接逗号串（{@code "1,2"}）。
     *
     * <p>两种形态都要收：管理端提交的是数组，而人工改过的历史配置 / 脚本多为逗号串；
     * 只认一种会让另一种<b>静默变成空清单</b> —— 而空清单在新语义下是「不可见」，
     * 一个解析差异就能把专家藏起来，代价太大。</p>
     */
    static List<Long> toLongList(Object v) {
        List<Long> out = new ArrayList<>();
        if (v == null) {
            return out;
        }
        if (v instanceof Iterable<?> it) {
            for (Object o : it) {
                Long n = toLong(o);
                if (n != null) {
                    out.add(n);
                }
            }
            return out;
        }
        for (String s : String.valueOf(v).split("[,\\s\\[\\]]+")) {
            Long n = toLong(s);
            if (n != null) {
                out.add(n);
            }
        }
        return out;
    }

    private static Long toLong(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof Number n) {
            return n.longValue();
        }
        String s = String.valueOf(o).trim();
        if (s.isEmpty()) {
            return null;
        }
        try {
            return Long.parseLong(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
