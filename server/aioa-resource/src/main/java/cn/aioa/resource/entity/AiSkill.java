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
 * 技能：用户端技能宫格；fields 为动态表单 schema，前端据此渲染表单。
 */
@Data
@TableName(value = "ai_skill", autoResultMap = true)
public class AiSkill {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String skillName;

    private String icon;

    /** 预估词元消耗，用于技能页「预计消耗」提示 */
    private Integer estTokens;

    @TableField(typeHandler = JsonListTypeHandler.class)
    private List<Object> fields;

    /** 归属专家（可空 = 通用技能） */
    private String expertKey;

    private Boolean enabled;

    private Integer sort;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
