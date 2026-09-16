package cn.aioa.gitee.service;

import cn.aioa.gitee.config.GiteeProperties;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.entity.GiteeTask;
import cn.aioa.gitee.mapper.GiteeProjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Map;

/**
 * 周期性轻量校准：把 Gitee 侧与平台侧的成员权限对齐。
 *
 * <p><b>为什么需要它</b>：成员同步是「事件驱动」的 —— 用户加/删成员才触发。
 * 但现实里 Gitee 侧会**漂移**：① 有人在 Gitee 网页端手工加了/删了协作者；
 * ② 成员当时还没绑定 Gitee，同步被挂起；③ 网络失败重试到上限后放弃。
 * 定时校准是唯一能收敛这些漂移的手段。</p>
 *
 * <p><b>为什么只入队、不在这里调 Gitee</b>：校准量 = 项目数，直接调会让调度线程被
 * 网络 IO 阻塞；更糟的是瞬间并发出网会触发 Gitee 的 403 Rate Limit Exceeded（实测）。
 * 入队后由 {@code GiteeTaskService} 以 batch=5 + 全局限流消费，把突发摊平。</p>
 *
 * <p><b>为什么限量 + 错峰</b>：单轮最多补 {@code MAX_PER_RUN} 条，宁可多跑几轮，
 * 也不让一次校准把队列塞满、把用户的交互式操作（建仓、加成员）挤到队尾；
 * 每条间隔 {@code STAGGER_SECONDS} 秒，把一轮校准摊开成若干秒。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class GiteeSyncScheduler {

    /** 单轮入队上限：超出留到下一轮，保证交互式任务优先。 */
    private static final int MAX_PER_RUN = 200;

    /** 每条任务之间的错峰间隔（秒）。 */
    private static final int STAGGER_SECONDS = 2;

    private final GiteeProperties props;
    private final GiteeProjectMapper projectMapper;
    private final GiteeTaskService taskService;

    /**
     * 定时校准入口。
     *
     * <p>cron 由 {@code aioa.gitee.sync-cron} 配置（默认每小时第 17 分 0 秒）。
     * 刻意避开整点：整点是各类定时任务的高峰。</p>
     */
    @Scheduled(cron = "${aioa.gitee.sync-cron:0 17 * * * *}")
    public void scheduledCalibrate() {
        if (!props.isEnabled() || !props.isSyncEnabled()) {
            return;
        }
        int n = calibrateAll(null);
        log.info("Gitee 定时校准：本轮入队 {} 条项目校准任务", n);
    }

    /**
     * 全量校准：为每个 ACTIVE 项目补一条 {@code SYNC_ALL} 任务。
     *
     * <p>只对 ACTIVE 项目做：CREATING（仓库还没建出来）与 FAILED（可能根本没有仓库）
     * 的项目去校准协作者只会白跑一轮外部调用。</p>
     *
     * @param tenantId 限定租户；{@code null} 表示全部租户（定时任务用）。
     *                 <b>手动触发必须传租户</b>：否则一个租户管理员点一下「立即校准」，
     *                 就会给其他所有租户的项目排上外部调用任务 —— 既是越权副作用，
     *                 也会平白消耗别人的 Gitee 配额。
     * @return 实际入队条数
     */
    public int calibrateAll(Long tenantId) {
        int budget = MAX_PER_RUN;
        int enqueued = 0;
        int stagger = 0;

        LambdaQueryWrapper<GiteeProject> q = new LambdaQueryWrapper<GiteeProject>()
                .eq(GiteeProject::getStatus, GiteeProject.STATUS_ACTIVE)
                .orderByAsc(GiteeProject::getId)
                .last("limit " + MAX_PER_RUN);
        if (tenantId != null) {
            q.eq(GiteeProject::getTenantId, tenantId);
        }
        List<GiteeProject> projects = projectMapper.selectList(q);
        for (GiteeProject p : projects) {
            if (budget <= 0) {
                break;
            }
            if (!StringUtils.hasText(p.getGiteeRepo()) || !StringUtils.hasText(p.getGiteeOwner())) {
                continue;
            }
            taskService.enqueue(p.getTenantId(), GiteeTask.TYPE_SYNC_ALL, "PROJECT", p.getId(),
                    Map.of("reason", "scheduled-calibrate"), stagger);
            stagger += STAGGER_SECONDS;
            enqueued++;
            budget--;
        }
        return enqueued;
    }

    /**
     * 手动触发校准（管理端排障用）。
     *
     * @param tenantId 限定租户；{@code null} 表示全部（仅平台管理员可用）
     * @return 入队条数
     */
    public int triggerCalibrateNow(Long tenantId) {
        return calibrateAll(tenantId);
    }
}
