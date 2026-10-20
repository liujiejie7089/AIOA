package cn.aios.resource.connector.mcp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * MCP 服务器注册表（docs/59 §10.3）。
 *
 * <p>范围语义：{@code tenant_id=0} 行是平台内置（BUILTIN，仅种子）；其余为租户自注册（EXTERNAL）。
 * 一行即一条 MCP 服务器，形如 {@code {name, source, transport, command+args+env | url+headers}}。</p>
 *
 * <p><b>信任闸门</b>：新服务器 {@code trusted=0}；{@code trust} 必须先探测，ok=true 才置 {@code trusted=1}
 * 并覆盖写工具目录。{@code manifest} 仅返回 {@code trusted=1} 且（BUILTIN ⇒ 连接器已 CONNECTED）的服务器。</p>
 */
@Data
@TableName("mcp_server")
public class McpServer {

    public static final String SOURCE_BUILTIN = "BUILTIN";
    public static final String SOURCE_EXTERNAL = "EXTERNAL";

    public static final String TRANSPORT_STDIO = "STDIO";
    public static final String TRANSPORT_STREAMABLE_HTTP = "STREAMABLE_HTTP";

    public static final String STATUS_UNKNOWN = "UNKNOWN";
    public static final String STATUS_OK = "OK";
    public static final String STATUS_ERROR = "ERROR";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String code;
    private String name;
    private String source;                 // BUILTIN | EXTERNAL
    private String transport;              // STDIO | STREAMABLE_HTTP
    private String command;
    private String argsJson;               // JSON 数组文本（明文，非密）
    private String envEnc;                 // 密文：JSON 对象文本（enc）
    private String url;
    private String headersEnc;             // 密文：JSON 对象文本（enc）
    private Integer trusted;               // 0=未信任 1=已信任
    private String status;                 // UNKNOWN | OK | ERROR
    private String lastError;
    private LocalDateTime lastProbeAt;
    private String connectorCode;          // BUILTIN 对应的连接器 code
    private Integer sort;
    private Long createdBy;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
