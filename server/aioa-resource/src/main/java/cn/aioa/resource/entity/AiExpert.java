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

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
