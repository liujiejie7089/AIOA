package cn.aios.resource.connector.mcp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * MCP 内置工具调用审计（docs/59 §10.3）。追加写、不可软删；只存参数 SHA-256 摘要，
 * <b>绝不</b>存参数原文（防止凭据/正文泄露）。
 */
@Data
@TableName("mcp_tool_audit")
public class McpToolAudit {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long userId;
    private String serverCode;
    private String toolName;
    private String argsDigest;
    private Integer ok;
    private String error;
    private Long durationMs;
    private LocalDateTime createdAt;
}
