-- 数字员工：可见范围（部门分发的数据基础）+ 模板来源追溯
-- visible_scope: TENANT=本租户全员可见（默认） / DEPT=仅指定部门可见
-- dept_ids:     visible_scope=DEPT 时的部门 id 列表，JSON 数组，如 [12,13]
-- source_template_id: 若由全局模板(tenant_id=0)复制而来，记录源模板 id，便于追溯与升级

ALTER TABLE agent_worker
    ADD COLUMN visible_scope VARCHAR(16) NOT NULL DEFAULT 'TENANT' COMMENT '可见范围: TENANT/DEPT' AFTER tenant_id,
    ADD COLUMN dept_ids      VARCHAR(512) NULL COMMENT '可见部门 id 列表(JSON数组), visible_scope=DEPT 时有效' AFTER visible_scope,
    ADD COLUMN source_template_id BIGINT NULL COMMENT '来源模板 id(tenant_id=0 的全局模板)' AFTER dept_ids;

-- 列表查询主路径：按租户 + 可见范围过滤
ALTER TABLE agent_worker
    ADD INDEX idx_worker_tenant_scope (tenant_id, visible_scope, deleted_at);

-- 全局模板标记：tenant_id=0 且 is_template=1 的作为可复制模板。
-- 复用 enabled 不足以表达「模板」语义，独立一列更清晰，且不影响既有查询。
ALTER TABLE agent_worker
    ADD COLUMN is_template TINYINT NOT NULL DEFAULT 0 COMMENT '是否为全局模板(1=是, 仅 tenant_id=0)' AFTER source_template_id;

-- 现有 4 条 tenant_id=0 的记录即为平台内置模板
UPDATE agent_worker SET is_template = 1 WHERE tenant_id = 0;
