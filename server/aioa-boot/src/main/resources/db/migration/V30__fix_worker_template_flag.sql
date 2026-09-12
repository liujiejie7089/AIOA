-- 修正 V29：标记模板时未排除软删记录，导致历史已删除的 tenant_id=0 记录也被标为模板。
-- 模板必须是「存在且可用」的样板，已软删的不应参与。
-- （不修改 V29 文件本身：Flyway 对已执行迁移做 checksum 校验，改内容会导致启动失败。）

UPDATE agent_worker
SET is_template = 0
WHERE tenant_id = 0
  AND deleted_at IS NOT NULL
  AND is_template = 1;
