package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户端操作记录（对应原型「我的操作记录」）。
 * status: ok / warn / fail；label 为右侧徽标文案。
 */
@Data
@TableName("client_activity_log")
public class ClientActivityLog {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    /** 动作主体，如「发起会话（政策咨询专家）」；前端再拼时间前缀 */
    private String action;

    private String status;

    private String label;

    /** 变更前快照（JSON 文本，V32）——历史行与无变更动作为 null。 */
    private String beforeValue;

    /** 变更后快照（JSON 文本，V32）。 */
    private String afterValue;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
