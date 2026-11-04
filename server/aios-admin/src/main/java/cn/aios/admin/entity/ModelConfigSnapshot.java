package cn.aios.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/**
 * 平台模型配置快照（2026-11-04，docs/72 §4）：每次写操作前落一份全量 JSON，
 * 用于「回滚到上一版」。快照里 api_key 保持密文原值，回滚时原样写回，不产生明文。
 */
@TableName("model_config_snapshot")
public class ModelConfigSnapshot {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** SAVE / DELETE / STATUS / DEFAULT / ROLLBACK */
    private String reason;

    private Integer total;

    private String snapshotJson;

    private Long operatorId;

    private LocalDateTime createdAt;

    public Long getId() { return id; }

    public void setId(Long id) { this.id = id; }

    public String getReason() { return reason; }

    public void setReason(String reason) { this.reason = reason; }

    public Integer getTotal() { return total; }

    public void setTotal(Integer total) { this.total = total; }

    public String getSnapshotJson() { return snapshotJson; }

    public void setSnapshotJson(String snapshotJson) { this.snapshotJson = snapshotJson; }

    public Long getOperatorId() { return operatorId; }

    public void setOperatorId(Long operatorId) { this.operatorId = operatorId; }

    public LocalDateTime getCreatedAt() { return createdAt; }

    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
