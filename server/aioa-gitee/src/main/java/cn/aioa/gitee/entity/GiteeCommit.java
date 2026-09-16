package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Gitee 提交记录（网页上传 + 本地 git push 两路合一）。
 *
 * <p>表 {@code gitee_commit}（V48）。无软删。</p>
 *
 * <p>两路来源：{@code WEB}（平台网页上传文件，后端经 contents 接口提交后直接落库）/
 * {@code GIT}（开发本地 push，经 Webhook 的 push 事件回传解析）。</p>
 *
 * <p>唯一键 {@code (project_id, sha)}：同一提交被重复投递、或同时出现在多次 push 事件里，
 * 都只保留一条 —— 「提交记录」应当按提交去重，而不是按投递次数堆叠。</p>
 */
@Data
@TableName("gitee_commit")
public class GiteeCommit {

    public static final String SOURCE_WEB = "WEB";
    public static final String SOURCE_GIT = "GIT";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** 提交 sha（统一存长 sha）。 */
    private String sha;

    private String branch;

    private String message;

    private String authorName;

    private String authorEmail;

    /** 作者 Gitee uid（可用于身份映射）。 */
    private Long giteeUid;

    /** 映射到的平台用户 id。 */
    private Long authorUserId;

    /** WEB / GIT。 */
    private String source;

    /** 来源事件 id（GIT 路径）。 */
    private Long eventId;

    private LocalDateTime committedAt;

    private LocalDateTime createdAt;
}
