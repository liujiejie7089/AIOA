package cn.aioa.org.mapper;

import cn.aioa.org.entity.OrgAuditLog;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** 两级审计日志 —— 复用 V1 audit_log（含防篡改哈希链） */
public interface OrgAuditLogMapper extends BaseMapper<OrgAuditLog> {
}
