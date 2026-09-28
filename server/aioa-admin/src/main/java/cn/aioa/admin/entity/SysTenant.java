package cn.aioa.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/**
 * 多租户最顶层隔离单元。
 *
 * <p>说明：表中已有 tenant_id / created_at / updated_at / created_by / deleted_at 列，
 * 但实体此前只映射了 id/name/code/status —— 导致租户自身的归属字段（tenant_id）无法读写，
 * 也没法走逻辑删除。这里补全，与其他业务表保持一致的隔离口径。
 * 租户的 tenant_id 自指（= 自身 id），便于与其它表统一按 tenant_id 过滤。</p>
 */
@TableName("sys_tenant")
public class SysTenant {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 自身归属：租户的 tenant_id 指向自身 id */
    private Long tenantId;

    private String code;

    private String name;

    private String status;

    /**
     * 平台分配的登录域名，如 {@code dsj.aioa.local}；未分配为 null（V66）。
     *
     * <p>2026-09-28：同批带来的 {@code parent_id} / {@code level}（租户层级）已随「子租户」能力一并移除
     * （V68 删列）；域名是独立能力，保留。</p>
     */
    private String domain;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getTenantId() {
        return tenantId;
    }

    public void setTenantId(Long tenantId) {
        this.tenantId = tenantId;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getDomain() {
        return domain;
    }

    public void setDomain(String domain) {
        this.domain = domain;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }

    public Long getCreatedBy() {
        return createdBy;
    }

    public void setCreatedBy(Long createdBy) {
        this.createdBy = createdBy;
    }

    public LocalDateTime getDeletedAt() {
        return deletedAt;
    }

    public void setDeletedAt(LocalDateTime deletedAt) {
        this.deletedAt = deletedAt;
    }
}
