package cn.aioa.gitee.service;

import cn.aioa.gitee.client.RepoProviderException;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteeTask;
import cn.aioa.gitee.mapper.GiteeTaskMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Gitee 异步任务队列（outbox）：入队 + 拉取执行 + 退避重试。
 *
 * <p><b>为什么需要它</b>（而不是在接口里直接调 Gitee）：</p>
 * <ol>
 *   <li>建项目要「建仓 → 配 Webhook → 同步成员」，是多次外部调用，同步做会让接口超时；</li>
 *   <li>Gitee 对高频请求返回 {@code 403 Rate Limit Exceeded}（已实测），必须串行节流；</li>
 *   <li>外部调用会失败，失败需要重试与可见的失败原因，而不是把异常抛给用户。</li>
 * </ol>
 *
 * <p><b>退避</b>：{@code 10s × 2^attempts}，封顶 10 分钟。只对
 * {@link RepoProviderException#isRetryable()} 的错误重试；参数类错误直接判死，
 * 避免把「仓库名重复」这种永久错误重试到上限、白白消耗配额。</p>
 *
 * <p><b>领取方式</b>：{@link GiteeTaskMapper#claim} 用条件 UPDATE 抢占，
 * 保证多实例 / 多线程下同一任务只被一个执行者拿到。</p>
 */
@Slf4j
@Service
public class GiteeTaskService {

    private final GiteeTaskMapper taskMapper;
    private final RepoProviderSettings props;
    private final ObjectMapper objectMapper;

    /**
     * 处理器集合**延迟解析**。
     *
     * <p>直接构造注入 {@code List<GiteeTaskHandler>} 会形成一个真实的构造环：
     * 项目服务 → 任务服务 → 校准处理器 → 成员服务 → 项目服务。
     * 队列本身并不需要在构造期就知道「谁在消费」，因此改成首次执行时再取 —— 环就断了。</p>
     */
    private final ObjectProvider<List<GiteeTaskHandler>> handlerProvider;

    private volatile Map<String, GiteeTaskHandler> handlers;

    /** 本实例标识（写入 locked_by，用于排障「是哪台机器在处理」）。 */
    private final String workerId;

    public GiteeTaskService(GiteeTaskMapper taskMapper, RepoProviderSettings props,
                            ObjectMapper objectMapper,
                            ObjectProvider<List<GiteeTaskHandler>> handlerProvider) {
        this.taskMapper = taskMapper;
        this.props = props;
        this.objectMapper = objectMapper;
        this.handlerProvider = handlerProvider;
        this.workerId = System.getProperty("aioa.worker.id", "aioa-gitee-1");
    }

    /** 任务类型 → 处理器。首次调用时构建并缓存。 */
    private Map<String, GiteeTaskHandler> handlers() {
        Map<String, GiteeTaskHandler> local = handlers;
        if (local == null) {
            synchronized (this) {
                local = handlers;
                if (local == null) {
                    local = handlerProvider.getObject().stream()
                            .flatMap(h -> h.types().stream().map(t -> Map.entry(t, h)))
                            .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue,
                                    (a, b) -> a, LinkedHashMap::new));
                    handlers = local;
                }
            }
        }
        return local;
    }

    // ======================================================================
    // 入队
    // ======================================================================

    /**
     * 入队一个任务。
     *
     * <p>入队与业务写库应在同一事务内（调用方加 {@code @Transactional}），
     * 否则「项目已建、任务没排上」会让项目永远停在 CREATING。</p>
     */
    public Long enqueue(Long tenantId, String taskType, String bizType, Long bizId, Map<String, Object> payload) {
        return enqueue(tenantId, taskType, bizType, bizId, payload, 0);
    }

    /** 立即执行（{@code delaySeconds=0}）或延迟执行。 */
    public Long enqueue(Long tenantId, String taskType, String bizType, Long bizId,
                        Map<String, Object> payload, int delaySeconds) {
        GiteeTask t = new GiteeTask();
        t.setTenantId(tenantId);
        t.setTaskType(taskType);
        t.setBizType(bizType);
        t.setBizId(bizId);
        t.setPayload(writeJson(payload));
        t.setStatus(GiteeTask.STATUS_PENDING);
        t.setAttempts(0);
        t.setMaxAttempts(props.getMaxAttempts());
        t.setNextRunAt(LocalDateTime.now().plusSeconds(Math.max(0, delaySeconds)));
        t.setCreatedAt(LocalDateTime.now());
        taskMapper.insert(t);
        return t.getId();
    }

    /**
     * 取消某业务对象下**尚未执行**的任务。
     *
     * <p>用于「项目已被删除，但建仓任务还在队列里」这类场景：
     * 不取消的话，用户删掉项目之后仓库又凭空建出来了。</p>
     */
    public int cancelPending(String bizType, Long bizId) {
        List<GiteeTask> list = taskMapper.selectList(new LambdaQueryWrapper<GiteeTask>()
                .eq(GiteeTask::getBizType, bizType)
                .eq(GiteeTask::getBizId, bizId)
                .eq(GiteeTask::getStatus, GiteeTask.STATUS_PENDING));
        int n = 0;
        for (GiteeTask t : list) {
            GiteeTask upd = new GiteeTask();
            upd.setId(t.getId());
            upd.setStatus(GiteeTask.STATUS_FAILED);
            upd.setLastError("业务对象已删除，任务被取消");
            upd.setUpdatedAt(LocalDateTime.now());
            n += taskMapper.updateById(upd);
        }
        return n;
    }

    // ======================================================================
    // 调度
    // ======================================================================

    /**
     * 拉取并执行任务。
     *
     * <p>固定延迟 3 秒轮询（而不是 cron）：队列需要「尽快」响应，秒级对用户已是准实时；
     * 同时 batch 限制为 5，天然形成对 Gitee 的节流。</p>
     */
    @Scheduled(fixedDelayString = "${aioa.gitee.task-poll-delay-ms:3000}", initialDelay = 8000)
    public void drain() {
        if (!props.isEnabled()) {
            return;
        }
        List<GiteeTask> candidates = taskMapper.selectList(new LambdaQueryWrapper<GiteeTask>()
                .eq(GiteeTask::getStatus, GiteeTask.STATUS_PENDING)
                .le(GiteeTask::getNextRunAt, LocalDateTime.now())
                .orderByAsc(GiteeTask::getId)
                .last("limit " + Math.max(1, props.getTaskBatchSize())));
        for (GiteeTask t : candidates) {
            if (taskMapper.claim(t.getId(), workerId, LocalDateTime.now()) != 1) {
                // 被别的执行者抢走了（或状态已变），跳过
                continue;
            }
            runOne(t);
        }
    }

    /** 执行单个任务并落状态。 */
    public void runOne(GiteeTask t) {
        GiteeTaskHandler handler = handlers().get(t.getTaskType());
        if (handler == null) {
            finish(t, GiteeTask.STATUS_FAILED, "无处理器：未知任务类型 " + t.getTaskType());
            return;
        }
        try {
            handler.handle(t);
            finish(t, GiteeTask.STATUS_DONE, null);
            log.info("Gitee 任务完成 id={} type={} biz={}#{}", t.getId(), t.getTaskType(), t.getBizType(), t.getBizId());
        } catch (RepoProviderException e) {
            if (e.isRetryable() && attempts(t) < maxAttempts(t)) {
                retry(t, e.getMessage());
            } else {
                finish(t, GiteeTask.STATUS_FAILED, e.getMessage());
            }
        } catch (Exception e) {
            log.warn("Gitee 任务异常 id={} type={}", t.getId(), t.getTaskType(), e);
            finish(t, GiteeTask.STATUS_FAILED, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    /** 立即执行某任务（同步，供「重试」按钮与管理端排障使用）。 */
    public void runNow(Long taskId) {
        GiteeTask t = taskMapper.selectById(taskId);
        if (t == null) {
            return;
        }
        if (taskMapper.claim(taskId, workerId, LocalDateTime.now()) != 1) {
            t.setStatus(GiteeTask.STATUS_PENDING);
        }
        runOne(t);
    }

    // ======================================================================
    // 内部
    // ======================================================================

    private void retry(GiteeTask t, String error) {
        int next = attempts(t) + 1;
        // 10s, 20s, 40s, 80s ... 封顶 10 分钟
        long delay = Math.min(600, (long) (10 * Math.pow(2, Math.max(0, next - 1))));
        GiteeTask upd = new GiteeTask();
        upd.setId(t.getId());
        upd.setStatus(GiteeTask.STATUS_PENDING);
        upd.setAttempts(next);
        upd.setNextRunAt(LocalDateTime.now().plusSeconds(delay));
        upd.setLastError(truncate(error));
        upd.setLockedBy(null);
        upd.setUpdatedAt(LocalDateTime.now());
        taskMapper.updateById(upd);
        log.info("Gitee 任务退避重试 id={} type={} attempt={} delay={}s err={}",
                t.getId(), t.getTaskType(), next, delay, truncate(error));
    }

    private void finish(GiteeTask t, String status, String error) {
        GiteeTask upd = new GiteeTask();
        upd.setId(t.getId());
        upd.setStatus(status);
        upd.setAttempts(attempts(t) + (GiteeTask.STATUS_FAILED.equals(status) ? 1 : 0));
        upd.setLastError(truncate(error));
        upd.setUpdatedAt(LocalDateTime.now());
        taskMapper.updateById(upd);
        if (GiteeTask.STATUS_FAILED.equals(status)) {
            log.warn("Gitee 任务失败 id={} type={} err={}", t.getId(), t.getTaskType(), error);
        }
    }

    private int attempts(GiteeTask t) {
        GiteeTask fresh = taskMapper.selectById(t.getId());
        Integer a = fresh == null ? t.getAttempts() : fresh.getAttempts();
        return a == null ? 0 : a;
    }

    private int maxAttempts(GiteeTask t) {
        Integer m = t.getMaxAttempts();
        return m == null || m <= 0 ? Math.max(1, props.getMaxAttempts()) : m;
    }

    private static String truncate(String s) {
        if (s == null) {
            return null;
        }
        return s.length() > 500 ? s.substring(0, 500) : s;
    }

    private String writeJson(Object o) {
        if (o == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }

    /** 读取任务参数。 */
    public Map<String, Object> payloadOf(GiteeTask t) {
        if (t.getPayload() == null || t.getPayload().isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(t.getPayload(), new com.fasterxml.jackson.core.type.TypeReference<>() {
            });
        } catch (Exception e) {
            return Map.of();
        }
    }

    /** 队列概览（管理端排障用）。 */
    public Map<String, Object> stats() {
        Map<String, Object> out = new LinkedHashMap<>();
        for (String s : List.of(GiteeTask.STATUS_PENDING, GiteeTask.STATUS_RUNNING,
                GiteeTask.STATUS_DONE, GiteeTask.STATUS_FAILED)) {
            out.put(s, taskMapper.selectCount(new LambdaQueryWrapper<GiteeTask>().eq(GiteeTask::getStatus, s)));
        }
        out.put("worker", workerId);
        return out;
    }
}
