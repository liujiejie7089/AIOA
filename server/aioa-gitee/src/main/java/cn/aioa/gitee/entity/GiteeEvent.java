package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Gitee 操作事件日志（Webhook 回传的落点）。
 *
 * <p>表 {@code gitee_event}（V48）。无软删 —— 事件是审计事实，只增不改。</p>
 *
 * <p><b>幂等</b>：Gitee 会重复投递同一事件。{@code eventKey} 由「事件类型 + 业务标识」拼成
 * 并建唯一索引，重复投递在插入时即被数据库拒绝 —— 用唯一键而不是「先查后插」，
 * 是因为并发投递下「先查后插」必然有竞态窗口。</p>
 *
 * <p><b>身份映射</b>：{@code actorGiteeUid} → {@code actorUserId}（未绑定则为空，
 * 前端回退显示 Gitee 登录名，而不是显示「未知用户」）。</p>
 */
@Data
@TableName("gitee_event")
public class GiteeEvent {

    public static final String TYPE_PUSH = "PUSH";
    public static final String TYPE_MERGE_REQUEST = "MERGE_REQUEST";
    public static final String TYPE_ISSUE = "ISSUE";
    public static final String TYPE_NOTE = "NOTE";
    public static final String TYPE_OTHER = "OTHER";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 命中的平台项目；未找到映射时为空。 */
    private Long projectId;

    /** PUSH / MERGE_REQUEST / ISSUE / NOTE / OTHER。 */
    private String eventType;

    /** Gitee 原始事件头（Push Hook / Merge Request Hook / Issue Hook / Note Hook）。 */
    private String giteeEvent;

    /** 幂等键（唯一）。 */
    private String eventKey;

    private String requestId;

    private String commitSha;

    /** 操作人 Gitee uid（身份映射输入）。 */
    private Long actorGiteeUid;

    private String actorLogin;

    /** 映射到的平台用户 id；未绑定为空。 */
    private Long actorUserId;

    /** 分支 / 标签 / 目标分支。 */
    private String refName;

    /** opened / closed / merged / comment 等。 */
    private String action;

    private String title;

    /** 一句话摘要（列表直接展示）。 */
    private String summary;

    /** 原始报文（排障用；列表接口不返回）。 */
    private String payload;

    private LocalDateTime occurredAt;

    private LocalDateTime receivedAt;
}
