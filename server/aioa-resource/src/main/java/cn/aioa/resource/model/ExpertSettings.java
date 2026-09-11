package cn.aioa.resource.model;

import lombok.Data;

import java.util.LinkedHashMap;
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

    /** 工具是否启用：未登记的工具默认启用（保证新增工具不会因缺配置而不可用）。 */
    public boolean toolEnabled(String name) {
        if (tools == null || !tools.containsKey(name)) {
            return true;
        }
        Boolean v = tools.get(name);
        return v == null || v;
    }
}
