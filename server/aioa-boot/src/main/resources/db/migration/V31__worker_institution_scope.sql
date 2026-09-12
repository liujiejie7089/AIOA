-- 数字员工归属机构：支撑「企业管理员只能管理本机构的数字员工」。
-- 此前 agent_worker 仅有 tenant_id，企业管理员（ROLE_ORG_ADMIN）一旦获得管理权，
-- 就能改删同租户下其他机构的数字员工——属越权缺口。
-- institution_id 为空表示租户级（由租户管理员创建，全租户共享）。

ALTER TABLE agent_worker
    ADD COLUMN institution_id BIGINT NULL COMMENT '归属机构 id，空=租户级' AFTER tenant_id;

ALTER TABLE agent_worker
    ADD INDEX idx_worker_inst (tenant_id, institution_id, deleted_at);

-- 历史数据按创建人回填归属机构；无法确定的留空（视为租户级，由租户管理员统管）
UPDATE agent_worker w
    JOIN org_member m ON m.user_id = w.created_by AND m.deleted_at IS NULL
SET w.institution_id = m.institution_id
WHERE w.institution_id IS NULL
  AND w.tenant_id <> 0;
