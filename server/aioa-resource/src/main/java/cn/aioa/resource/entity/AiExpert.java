package cn.aioa.resource.entity;

import cn.aioa.common.mybatis.JsonListTypeHandler;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 专家：用户端首页 / 专家页的卡片来源，同时携带推荐问题（recs）。
 */
@Data
@TableName(value = "ai_expert", autoResultMap = true)
public class AiExpert {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 前端稳定标识（policy / legal / startup / doc） */
    private String expertKey;

    private String name;

    private String icon;

    /** 一句话简介（列表副标题） */
    private String summary;

    /** 详情页介绍 */
    private String intro;

    @TableField(typeHandler = JsonListTypeHandler.class)
    private List<Object> tags;

    @TableField(typeHandler = JsonListTypeHandler.class)
    private List<Object> recs;

    private String agentCode;

    private Boolean enabled;

    private Integer sort;

    /** 领域分类：LEGAL/LABOR/CONTRACT/IP/COMPLIANCE/TAX/DATA。 */
    private String category;

    /** 模板版本，模板升级时用于提示租户。 */
    private String templateVersion;

    /** 租户副本指向的全局模板ID；全局模板自身为 null。 */
    private Long sourceTemplateId;

    /** 可见范围：ALL/TENANT/INSTITUTION/DEPT/USER（细粒度过滤在 expert_config 中）。 */
    private String visibleScope;

    /** 知识库范围：ALL 或逗号分隔的文档ID。 */
    private String kbScope;

    /** 新用户是否默认挂载。 */
    private Boolean defaultEnabled;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
