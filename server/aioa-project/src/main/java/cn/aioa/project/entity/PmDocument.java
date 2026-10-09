package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 项目 / 企业文档索引。表 {@code pm_document}（V72）。字节实体落既有 {@code sys_file}。
 *
 * <p>设计依据 {@code docs/40 §6.2} + {@code docs/43}。用户关键词：
 * 「所有文档（外部，大模型创建）」—— 由 {@link #source} 区分。</p>
 *
 * <p><b>两类来源</b>（{@link #source}）：</p>
 * <ul>
 *   <li>{@link #SOURCE_UPLOAD} 外部上传：先经 {@code POST /api/v1/files/upload} 落 {@code sys_file}，
 *       再把 {@code fileId} 挂到本表；{@link #contentText} 为空。</li>
 *   <li>{@link #SOURCE_AI} 大模型创建：由项目数字人生成，正文落 {@link #contentText}
 *       （并可同时落 {@code sys_file} 供下载），便于在线预览、检索与审计。</li>
 * </ul>
 *
 * <p>生成列 {@code alive} 不映射（V24 约定）。</p>
 */
@Data
@TableName("pm_document")
public class PmDocument {

    /** 来源：外部上传。 */
    public static final String SOURCE_UPLOAD = "UPLOAD";
    /** 来源：大模型创建。 */
    public static final String SOURCE_AI = "AI";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long folderId;

    /** 冗余项目维度（企业级文档为 0），便于按项目聚合。 */
    private Long projectId;

    private String name;

    /** sys_file.id（字节实体）；AI 生成时同样先落盘再挂，可为空。 */
    private Long fileId;

    /** UPLOAD / AI，见本类常量。 */
    private String source;

    /** AI 生成文档的正文（便于在线预览与检索；上传件为空）。允许改空 ⇒ 更新策略 ALWAYS。 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private String contentText;

    private Long sizeBytes;

    /** 同名覆盖时自增。 */
    private Integer version;

    private String tags;

    /** 上传人 / 生成人 sys_user.id。 */
    private Long uploadedBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
