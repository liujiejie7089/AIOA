package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 表单定义版本快照（docs/52 P1，范式照 ApprovalFlowDefVersion）。
 *
 * <p>改定义必留旧版：{@code form_template.version + 1} 后，把新版本的 schema/layout/receipt
 * 写入本表，旧版本行永不覆盖、可随时回查。本表无逻辑删除（版本快照是只读归档）。</p>
 */
@Data
@TableName("form_template_version")
public class FormTemplateVersion {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** form_template.id。 */
    private Long templateId;

    /** 版本号（从 1 递增，永不覆盖）。 */
    private Integer version;

    /** 该版本 schema 快照。 */
    private String schemaJson;

    /** 该版本 layout 快照。 */
    private String layoutJson;

    /** 该版本回执快照。 */
    private String receiptJson;

    private Long createdBy;

    private LocalDateTime createdAt;
}
