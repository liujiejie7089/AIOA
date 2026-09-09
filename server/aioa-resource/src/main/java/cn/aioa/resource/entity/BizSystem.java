package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 已接入的业务系统（V15）：管理端统一注册与维护。
 * 记录接口地址、认证方式与密钥、接口文档，供统一管理与后续工具网关准入校验。
 * authType: NONE 无认证 / API_KEY 请求头密钥 / BASIC 基础认证 / BEARER 令牌。
 */
@Data
@TableName("biz_system")
public class BizSystem {

    public static final String AUTH_NONE = "NONE";
    public static final String AUTH_API_KEY = "API_KEY";
    public static final String AUTH_BASIC = "BASIC";
    public static final String AUTH_BEARER = "BEARER";

    public static final String STATUS_ENABLED = "ENABLED";
    public static final String STATUS_DISABLED = "DISABLED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 系统编码（租户内唯一） */
    private String systemCode;

    private String name;

    private String description;

    /** 接口根地址 */
    private String baseUrl;

    /** 认证方式：NONE / API_KEY / BASIC / BEARER */
    private String authType;

    /** 认证配置 JSON（密钥等敏感信息，接口返回时掩码） */
    private String authConfig;

    /** 接口文档链接 */
    private String docUrl;

    /** 接口文档内容（Markdown / 纯文本） */
    private String docContent;

    /** ENABLED / DISABLED */
    private String status;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
