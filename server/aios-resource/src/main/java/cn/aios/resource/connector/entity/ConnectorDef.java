package cn.aios.resource.connector.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 连接器目录（平台级，tenant_id=0）。见 docs/58 §5。
 */
@Data
@TableName("connector_def")
public class ConnectorDef {

    public static final String AUTH_MODE_CREDENTIAL = "CREDENTIAL";
    /**
     * 历史值：自建应用网页授权（企业微信 {@code wechat_work} 曾用）。该连接器已于 2026-10-30
     * 下线并物理删除（docs/64 §9.7），库里仍可能留有 {@code status=DISABLED} 的行，
     * 但没有任何 ACTIVE 连接器使用本形态，Java 侧也不再实现 OAUTH2 分支。
     */
    public static final String AUTH_MODE_OAUTH2 = "OAUTH2";
    /**
     * 历史值：租户级凭据（管理员填 key，无用户授权环节），企业微信群机器人曾用。
     * 该连接器已于 2026-10-30 下线并物理删除（docs/64 §9.7）。
     */
    public static final String AUTH_MODE_API_KEY = "API_KEY";
    /**
     * 扫码授权（用户手机扫二维码，凭据落在**该用户自己的**本地配置目录里），如企业微信官方
     * {@code wecom-cli} 连接器（docs/64）。
     *
     * <p>与 OAUTH2 的区别不在「有没有授权」，而在<b>凭据存在哪</b>：OAUTH2 拿到的是 token，
     * 存在 MySQL（加密）后由 Java 用它调开放接口；QR 拿到的是 CLI 自己加密落盘的 credentials，
     * 只存在于 hub 侧的用户目录，Java 完全不持有、也无法解出。因此 OAUTH2 那套
     * {@code start/callback} 流程对 QR 完全不适用 —— 那套代码已随 wechat_work 删除。</p>
     */
    public static final String AUTH_MODE_QR = "QR";
    public static final String STATUS_ACTIVE = "ACTIVE";

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String code;
    private String name;
    private String groupName;
    private String icon;
    private String summary;
    private String authMode;
    /** 应用配置键（JSON 数组文本，如 ["corpId","agentId","corpSecret"]）；读时按需要解析。 */
    private String configKeys;
    private String helpText;
    private String helpUrl;
    private Integer sort;
    private String status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private LocalDateTime deletedAt;
}
