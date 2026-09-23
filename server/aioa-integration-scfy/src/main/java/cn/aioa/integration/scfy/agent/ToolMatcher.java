package cn.aioa.integration.scfy.agent;

import java.util.List;

/**
 * 语义匹配器 —— 「用自然语言提问」→「该调哪个接口」。
 *
 * <p><b>为什么是接口而不是一个 final 类</b>：匹配质量与成本是一对矛盾。
 * 纯词法匹配零成本、离线可测、结果确定，但遇到「换个说法」就不如向量或大模型。
 * 这里不预判哪个更好，而是把匹配这一层做成可替换的插槽：默认给确定性实现
 * （离线可测、结果可复现），将来若要换成向量检索或大模型选工具，
 * 只需再实现本接口并覆盖 Bean —— <b>调用方（服务层、工具层、注册表）一行都不用改</b>。</p>
 *
 * <p>接口刻意只收「提问 + 候选集 + 取前几名」，不暴露任何内部打分细节：
 * 一旦把分数语义写进接口，替换实现就会被分数口径绑架。</p>
 */
public interface ToolMatcher {

    /** 实现名 —— 写进结果与日志，便于回答「这次匹配是谁做的」。 */
    String name();

    /**
     * 按相关度排序候选接口。
     *
     * @param question   用户原话
     * @param candidates 参与匹配的接口（已由注册表筛过「可自动调用」）
     * @param topN       最多返回几条
     * @return 按相关度降序的匹配结果；无任何相关时返回空列表
     */
    List<Match> rank(String question, List<ScfyToolDescriptor> candidates, int topN);

    /**
     * 低于这个分数视为「没有匹配」。
     *
     * <p>服务层用它决定「是自动调用，还是如实告诉用户查不了」——
     * 宁可回一句「我不确定该用哪个查询」，也不要在低置信度下随便挑一个接口，
     * 然后给用户一份与问题无关的数据。</p>
     */
    double minScore();

    /**
     * 一条匹配结果。
     *
     * @param tool    命中的接口
     * @param score   相关度（0~1）
     * @param reasons 为什么命中（命中词 / 命中分组），用于让用户与运维看懂结论从何而来
     */
    record Match(ScfyToolDescriptor tool, double score, List<String> reasons) {

        /** 一行摘要，供候选列表回显。 */
        public String line() {
            return String.format("%.3f  %s%s", score, tool.shortLine(),
                    reasons.isEmpty() ? "" : "（命中：" + String.join("、", reasons) + "）");
        }
    }
}
