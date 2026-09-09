package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 经营数据看板 —— AI 解读与数据来源（V1.2 新增）。
 * 每个租户每个 period 一条（uk: tenant_id + period + deleted_at）。
 */
@Data
@TableName("biz_kpi_insight")
public class BizKpiInsight {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String period;

    /** 解读正文 */
    private String content;

    /** 数据来源说明，展示在看板底部 */
    private String sourceText;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
