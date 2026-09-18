package cn.aioa.gitee.service;

import cn.aioa.gitee.entity.GiteeTask;

/**
 * 异步任务处理器。
 *
 * <p><b>为什么要抽这一层</b>：任务由「谁」执行与「谁」入队必须解耦 ——
 * 入队方（项目服务 / 成员服务）与执行方（需要出网调 Gitee）若互相依赖，就会形成
 * Spring 的循环依赖。处理器只依赖「Gitee 客户端 + 令牌 + 数据表」，
 * 由 {@link GiteeTaskService} 通过 {@code List<GiteeTaskHandler>} 收集并分发。</p>
 *
 * <p><b>异常约定</b>：抛 {@link cn.aioa.gitee.client.RepoProviderException}（托管方中立基类，
 * 两家的实现都继承它）且 {@code retryable=true} 时由调度器退避重试；其余异常一律视为永久失败，
 * 直接落 {@code FAILED} 并写 {@code last_error}（避免把参数错误重试到天花板）。</p>
 *
 * <p>⚠️ 处理器**不要**按 Gitee 专有类型 {@code GiteeApiException} 去 catch：Gitea 侧抛的是
 * 中立基类，按专有类型捕获会漏接，症状是「幂等/认领这类兜底逻辑在 Gitea 下静默失效」。</p>
 */
public interface GiteeTaskHandler {

    /**
     * 本处理器负责的任务类型集合。
     *
     * <p>返回集合而非单值：仓库生命周期的「建仓 / 配 Webhook / 删仓」共享同一套
     * 「取项目 + 取令牌 + 失败落状态」的前置逻辑，拆成三个类只会重复三遍。</p>
     */
    java.util.List<String> types();

    /** 执行任务；抛异常即视为失败。 */
    void handle(GiteeTask task) throws Exception;
}
