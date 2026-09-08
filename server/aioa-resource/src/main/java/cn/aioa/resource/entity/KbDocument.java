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

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    private String docName;

    private String icon;

    private String state;

    private Long sizeBytes;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
