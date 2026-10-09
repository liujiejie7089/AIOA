package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 项目上下文来源。表 {@code pm_context_source}（V74）。设计依据 {@code docs/43 §5.2/§5.3}。
 *
 * <p>用户关键词「项目上下文控制」= 对数字人在本项目里可用的**知识来源**做开关与范围控制。
 * 三类来源同表用 {@link #sourceType} 区分（同 docs/40 §8.3「同表 + 判别列」取舍）：</p>
 * <table border="1">
 *   <tr><th>source_type</th><th>含义</th><th>关键列</th></tr>
 *   <tr><td>{@link #SOURCE_UPLOAD}</td><td>后台上传</td><td>{@link #folderId}（整目录）/ {@link #fileId}（单文件）</td></tr>
 *   <tr><td>{@link #SOURCE_WEB_SEARCH}</td><td>网上搜索</td><td>{@link #config}（{@code {keywords,domains,maxResults}}）</td></tr>
 *   <tr><td>{@link #SOURCE_POLICY}</td><td>政策</td><td>{@link #kbDocumentId}（政策知识库文档）</td></tr>
 * </table>
 *
 * <p>{@link #workerId}=0 表示「项目级默认上下文」（对所有已分配数字人生效）；否则仅对该数字员工。</p>
 *
 * <p>生成列 {@code alive} 不映射（V24 约定）。</p>
 */
@Data
@TableName("pm_context_source")
public class PmContextSource {

    /** 来源类型：后台上传（项目文档 / 指定文件夹）。 */
    public static final String SOURCE_UPLOAD = "UPLOAD";
    /** 来源类型：网上搜索（关键词/域名/条数）。 */
    public static final String SOURCE_WEB_SEARCH = "WEB_SEARCH";
    /** 来源类型：政策（政策知识库文档）。 */
    public static final String SOURCE_POLICY = "POLICY";

    /** {@link #workerId} 取此值 = 项目级默认上下文（对所有已分配数字人生效）。 */
    public static final long WORKER_DEFAULT = 0L;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** 0=项目级默认；否则仅对该 {@code agent_worker.id}。 */
    private Long workerId;

    /** UPLOAD / WEB_SEARCH / POLICY，见本类常量。 */
    private String sourceType;

    /** 来源显示名。 */
    private String name;

    /** UPLOAD：指向 {@code pm_folder}（整目录纳入）。 */
    private Long folderId;

    /** UPLOAD：指向 {@code sys_file}（单文件纳入）。 */
    private Long fileId;

    /** POLICY：指向 {@code kb_document}（政策库文档）。 */
    private Long kbDocumentId;

    /** WEB_SEARCH：{@code {"keywords":[...],"domains":[...],"maxResults":N}}。 */
    private String config;

    /** 0=已关闭（保留配置但不参与上下文组装）。 */
    private Integer enabled;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;

    /** 是否为项目级默认上下文（对所有已分配数字人生效）。 */
    public boolean isProjectDefault() {
        return workerId == null || workerId == WORKER_DEFAULT;
    }
}
