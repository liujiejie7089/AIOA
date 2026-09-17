package cn.aioa.resource.service.notify;

import java.util.Map;

/**
 * 单次投递上下文：分发器组装后交给 {@link NotificationChannel#send(DeliveryContext)}。
 *
 * <p>{@code to} 为解析后的收件地址（EMAIL=邮箱；SMS/PUSH 当前数据模型未建模，恒为 null）。
 * {@code config} 为该通道的网关配置（config_json 解析后的 Map，含全部未知键以保无损）。</p>
 */
public class DeliveryContext {

    /** 租户 id */
    private Long tenantId;
    /** 关联站内通知 id（可能为 null） */
    private Long notificationId;
    /** 接收人 user_id */
    private Long userId;
    /** 通知类型 */
    private String type;
    /** 标题 */
    private String title;
    /** 正文 */
    private String content;
    /** 关联业务 id（可空） */
    private Long refId;
    /** 该通道网关配置（config_json 解析） */
    private Map<String, Object> config;
    /** 解析出的收件地址（可能为 null） */
    private String to;

    public Long getTenantId() {
        return tenantId;
    }

    public void setTenantId(Long tenantId) {
        this.tenantId = tenantId;
    }

    public Long getNotificationId() {
        return notificationId;
    }

    public void setNotificationId(Long notificationId) {
        this.notificationId = notificationId;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public Long getRefId() {
        return refId;
    }

    public void setRefId(Long refId) {
        this.refId = refId;
    }

    public Map<String, Object> getConfig() {
        return config;
    }

    public void setConfig(Map<String, Object> config) {
        this.config = config;
    }

    public String getTo() {
        return to;
    }

    public void setTo(String to) {
        this.to = to;
    }
}
