package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 知识库资料：用户端「我的知识库」文件清单。
 * state: OK 已入库 / WAIT 解析中 / FAILED 解析失败。
 */
@Data
@TableName("kb_document")
public class KbDocument {

    public static final String STATE_OK = "OK";
    public static final String STATE_WAIT = "WAIT";
    public static final String STATE_FAILED = "FAILED";

    /** 可见范围：个人（仅本人可见）。 */
    public static final String SCOPE_PERSONAL = "PERSONAL";
    /** 可见范围：租户共享（同租户全员可见、可被全员检索）。 */
    public static final String SCOPE_TENANT = "TENANT";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    private String docName;

    private String icon;

    private String state;

    private Long sizeBytes;

    /** 资料正文：上传时携带，切片后入库，供检索与引用溯源使用。 */
    private String content;

    /** 可见范围：PERSONAL 个人 / TENANT 租户共享。 */
    private String scope;

    /** 切片数量（入库成功后回填）。 */
    private Integer chunkCount;

    /** 入库失败原因（state=FAILED 时有值，前端可展示并支持重试）。 */
    private String errorMsg;

    /** 入库完成时间。 */
    private LocalDateTime indexedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
