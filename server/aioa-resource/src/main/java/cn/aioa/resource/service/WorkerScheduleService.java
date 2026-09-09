package cn.aioa.resource.service;

import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.AgentWorkerRun;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.AgentWorkerRunMapper;
import cn.aioa.resource.mapper.NotificationMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * 数字员工真实定时任务（V15）：
 *   · 每分钟扫描启用中且配置了执行时刻（HH:mm）的数字员工；
 *   · 到点即调 agent {@code /internal/v1/complete} 真实执行任务内容（模型生成）；
 *   · 每次执行落 {@code agent_worker_run} 留痕，并更新员工最近产出；
 *   · 执行完成给租户全员发 WORKER 站内通知（用户端轮询后弹窗提醒）。
 *
 * <p>防重复：同一天同一时刻只执行一次（lastRunAt 与今天比较），
 * 应用重启不会重放当天已执行的任务。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerScheduleService {

    private static final DateTimeFormatter HH_MM = DateTimeFormatter.ofPattern("HH:mm");

    private final AgentWorkerMapper workerMapper;
    private final AgentWorkerRunMapper runMapper;
    private final NotificationMapper notificationMapper;
    private final NotificationService notificationService;
    private final ActivityLogService activityLogService;
    private final ObjectMapper objectMapper;

    @Value("${aioa.agent.base-url:http://localhost:8000}")
    private String agentBaseUrl;

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    /** 每分钟整分扫描：匹配执行时刻的数字员工到点执行。 */
    @Scheduled(cron = "0 * * * * *")
    public void tick() {
        LocalTime now = LocalTime.now();
        String nowStr = now.format(HH_MM);
        List<AgentWorker> workers = workerMapper.selectList(new LambdaQueryWrapper<AgentWorker>()
                .eq(AgentWorker::getEnabled, 1)
                .isNotNull(AgentWorker::getScheduleTime)
                .eq(AgentWorker::getScheduleTime, nowStr));
        for (AgentWorker worker : workers) {
            if (alreadyRanToday(worker)) {
                continue;
            }
            try {
                runNow(worker, AgentWorkerRun.TRIGGER_SCHEDULE);
            } catch (Exception e) {
                log.error("数字员工定时任务执行失败 worker={}", worker.getId(), e);
            }
        }
    }

    /** 同一天已执行过则跳过（重启不重放）。 */
    private boolean alreadyRanToday(AgentWorker worker) {
        if (worker.getLastRunAt() == null) {
            return false;
        }
        LocalDate today = LocalDate.now();
        return worker.getLastRunAt().toLocalDate().isEqual(today);
    }

    /**
     * 真实执行一次数字员工任务（定时到点 / 管理端手动触发共用）：
     * 调 agent 非流式补全 → 写执行记录 → 更新员工最近产出 → 租户全员通知。
     */
    public AgentWorkerRun runNow(AgentWorker worker, String triggerType) {
        LocalDateTime startedAt = LocalDateTime.now();
        AgentWorkerRun run = new AgentWorkerRun();
        run.setTenantId(worker.getTenantId());
        run.setWorkerId(worker.getId());
        run.setWorkerName(worker.getName());
        run.setTriggerType(triggerType == null ? AgentWorkerRun.TRIGGER_SCHEDULE : triggerType);
        run.setStartedAt(startedAt);
        run.setCreatedAt(startedAt);

        String output = null;
        String errorMsg = null;
        String model = null;
        long begin = System.currentTimeMillis();
        try {
            String prompt = worker.getTaskPrompt();
            if (prompt == null || prompt.isBlank()) {
                errorMsg = "未配置任务内容（taskPrompt 为空）";
            } else {
                CompleteResult result = callAgentComplete(worker, prompt);
                model = result.model;
                if (result.error != null) {
                    errorMsg = result.error;
                } else {
                    output = result.content;
                }
            }
        } catch (Exception e) {
            log.error("数字员工执行异常 worker={} {}", worker.getId(), worker.getName(), e);
            errorMsg = "执行异常：" + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
        }
        run.setDurationMs(System.currentTimeMillis() - begin);
        run.setFinishedAt(LocalDateTime.now());
        run.setModel(model);
        if (output != null && !output.isBlank()) {
            run.setStatus(AgentWorkerRun.STATUS_SUCCESS);
            run.setOutput(output);
        } else {
            run.setStatus(AgentWorkerRun.STATUS_FAILED);
            run.setErrorMsg(errorMsg == null ? "执行失败" : errorMsg);
        }
        runMapper.insert(run);

        // 操作审计留痕：数字员工真实执行记录（管理端审计页可见）
        try {
            activityLogService.record(worker.getTenantId(), null,
                    "数字员工执行（" + worker.getName() + "）",
                    AgentWorkerRun.STATUS_SUCCESS.equals(run.getStatus()) ? "ok" : "fail",
                    AgentWorkerRun.TRIGGER_MANUAL.equals(run.getTriggerType()) ? "手动触发" : "定时执行");
        } catch (Exception e) {
            log.warn("数字员工执行审计留痕失败 worker={}", worker.getId(), e);
        }

        // 回写员工：最近产出摘要 + 最近执行时间（定时触发才更新 lastRunAt，防同日重复）
        AgentWorker patch = new AgentWorker();
        patch.setId(worker.getId());
        if (AgentWorkerRun.TRIGGER_SCHEDULE.equals(run.getTriggerType())) {
            patch.setLastRunAt(run.getStartedAt());
        }
        patch.setLastOutput(summarize(run));
        patch.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(patch);

        // 站内通知租户全员（TYPE_WORKER，用户端轮询到未读后弹窗提醒）
        notifyTenant(worker, run);
        return run;
    }

    /** 调 agent /internal/v1/complete 非流式补全。 */
    private CompleteResult callAgentComplete(AgentWorker worker, String prompt) throws Exception {
        String system = "你是 AIOA 智能办公平台的数字员工「" + worker.getName() + "」。"
                + "请以简洁、专业、可直接使用的方式完成任务；输出为纯文本，不要 markdown 代码围栏。"
                + (worker.getDescription() == null || worker.getDescription().isBlank()
                ? "" : "岗位职责：" + worker.getDescription());
        String body = objectMapper.writeValueAsString(java.util.Map.of(
                "prompt", prompt,
                "system", system,
                "max_tokens", 1024));
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(agentBaseUrl + "/internal/v1/complete"))
                .timeout(Duration.ofSeconds(150))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() / 100 != 2) {
            return new CompleteResult(null, null, "agent 服务返回 HTTP " + resp.statusCode());
        }
        JsonNode node = objectMapper.readTree(resp.body());
        String content = node.path("content").asText(null);
        String error = node.hasNonNull("error") ? node.get("error").asText() : null;
        String model = node.path("model").asText(null);
        return new CompleteResult(content, model, error);
    }

    /** 通知租户全员：成功给产出摘要，失败给原因。 */
    private void notifyTenant(AgentWorker worker, AgentWorkerRun run) {
        try {
            List<Long> userIds = notificationMapper.selectTenantUserIds(worker.getTenantId());
            boolean success = AgentWorkerRun.STATUS_SUCCESS.equals(run.getStatus());
            String title = success
                    ? "数字员工已完成：" + worker.getName()
                    : "数字员工执行失败：" + worker.getName();
            String content = success
                    ? "「" + worker.getName() + "」已完成定时任务，产出："
                    + truncate(run.getOutput(), 200)
                    : "「" + worker.getName() + "」执行失败：" + truncate(run.getErrorMsg(), 200);
            for (Long uid : userIds) {
                notificationService.notifyUser(worker.getTenantId(), uid, null,
                        cn.aioa.resource.entity.Notification.TYPE_WORKER, title, content, run.getId());
            }
        } catch (Exception e) {
            log.warn("数字员工执行通知失败（不影响执行结果）worker={}", worker.getId(), e);
        }
    }

    private static String summarize(AgentWorkerRun run) {
        return AgentWorkerRun.STATUS_SUCCESS.equals(run.getStatus())
                ? "[" + run.getStartedAt().format(DateTimeFormatter.ofPattern("MM-dd HH:mm")) + "] "
                + truncate(run.getOutput(), 300)
                : "[" + run.getStartedAt().format(DateTimeFormatter.ofPattern("MM-dd HH:mm")) + "] 执行失败："
                + truncate(run.getErrorMsg(), 200);
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        String one = s.replaceAll("\\s+", " ").trim();
        return one.length() <= max ? one : one.substring(0, max) + "…";
    }

    /** agent 补全结果载体。 */
    private record CompleteResult(String content, String model, String error) {
    }
}
