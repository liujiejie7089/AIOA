package cn.aios.resource.connector.mcp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 信任探活后登记的工具清单（docs/59 §10.3）。每次信任成功按 name 全量覆盖写某服务器下的行，
 * 多余行逻辑删除（{@code deletedAt}）。
 */
@Data
@TableName("mcp_server_tool")
public class McpServerTool {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long serverId;
    private String name;
    private String description;
    private String inputSchema;          // 工具输入 schema（JSON，MEDIUMTEXT）
    private Integer readOnly;            // 0=可写 1=只读
    private Integer sort;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
