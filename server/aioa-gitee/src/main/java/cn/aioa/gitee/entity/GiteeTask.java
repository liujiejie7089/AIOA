package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Gitee 异步任务队列（outbox）。
 *
 * <p>表 {@code gitee_task}（V48）。无软删 —— 任务历史是排障依据。</p>
 *
 * <p><b>为什么是 DB 队列而不是 MQ / Redis</b>：本部署没有可用的 Redis（配置里存在但健康检查被关），
 * 引入外部中间件会把「Gitee 联动」变成「部署必装 Redis」。落库 + {@code @Scheduled} 轮询
 * 用最小的运维面换取同样的能力。</p>
 *
 * <p><b>为什么必须异步</b>：建仓 → 配 Webhook → 同步成员是多次外部调用，同步执行会让
 * 「新建项目」接口超时；且 Gitee 对高频请求返回 {@code 403 Rate Limit Exceeded}（实测），
 * 必须串行节流。</p>
 *
 * <p><b>领取的并发安全</b>：{@code UPDATE ... SET status='RUNNING', locked_by=? WHERE id=? AND status='PENDING'}
 * —— 依赖这条 UPDATE 的原子性，而不是「先查后改」。</p>
 */
@Data
@TableName("gitee_task")
public class GiteeTask {

    // ---- 任务类型 ----
    public static final String TYPE_CREATE_REPO = "CREATE_REPO";
    public static final String TYPE_CONFIGURE_WEBHOOK = "CONFIGURE_WEBHOOK";
    public static final String TYPE_SYNC_MEMBER = "SYNC_MEMBER";
    public static final String TYPE_DELETE_REPO = "DELETE_REPO";
    /** 摘掉平台挂的 Webhook（删项目但保留仓库时必须做，否则钩子会一直打向已删除的项目）。 */
    public static final String TYPE_DELETE_WEBHOOK = "DELETE_WEBHOOK";
    public static final String TYPE_SYNC_ALL = "SYNC_ALL";

    // ---- 状态 ----
    public static final String STATUS_PENDING = "PENDING";
    public static final String STATUS_RUNNING = "RUNNING";
    public static final String STATUS_DONE = "DONE";
    public static final String STATUS_FAILED = "FAILED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** CREATE_REPO / CONFIGURE_WEBHOOK / SYNC_MEMBER / DELETE_REPO / SYNC_ALL。 */
    private String taskType;

    /** PROJECT / MEMBER。 */
    private String bizType;

    private Long bizId;

    /** 任务参数（JSON 字符串）。 */
    private String payload;

    /** PENDING / RUNNING / DONE / FAILED。 */
    private String status;

    private Integer attempts;

    private Integer maxAttempts;

    /** 下次可执行时间（失败退避）。 */
    private LocalDateTime nextRunAt;

    private LocalDateTime lockedAt;

    private String lockedBy;

    private String lastError;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
