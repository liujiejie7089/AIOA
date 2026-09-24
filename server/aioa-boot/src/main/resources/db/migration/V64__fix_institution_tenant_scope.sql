-- V64：修复「新增机构不显示」遗留的孤行（tenant_id = 0）
--
-- 背景：InstitutionService.create/update/changeStatus/assignAdmin 曾用**裸** AuthUser.tenantId
-- 作作用租户，而列表/详情用 OrgGuard.resolveRequestTenant。两者口径不一致：
--   平台管理员（ROLE_ADMIN）的 tenantId 恒为 0（平台自身租户）
--   ⇒ 平台管理员建的机构落到 tenant_id = 0
--   ⇒ 而列表按 resolveRequestTenant 得到的业务租户（如 2）过滤，永远查不到它
-- 现象：管理端「新增机构」成功后列表里没有它（实测留痕 org_institution id=87 code='ttt'）。
--
-- 代码侧已统一为 resolveRequestTenant（同 docs/24 的范围纪律）；本迁移修历史数据。
-- 回填目标 = 与 OrgGuard.defaultTenantId() 同一口径：
--   「机构数量最多的启用租户」（不取 id 最小 —— id=1 的默认租户名下 0 家机构，
--     回填过去会立刻再次落回空态，让「已修复」看起来仍然没修好）。
--
-- 只动 tenant_id = 0（或 NULL）这一种确定损坏的行，不触碰任何正常数据。
--
-- 为什么先落临时表再 UPDATE：MySQL 不允许「UPDATE 的目标表出现在子查询的 FROM 里」
-- （Error 1093: You can't specify target table for update in FROM clause）。
-- 直接把统计子查询写进 UPDATE 的 SET 里会直接失败（本迁移第一版就是这么挂的）。
-- 故先把目标租户算好存进临时表，再让 UPDATE 只读这个临时表。
-- 用 TEMPORARY 表而非普通表：Flyway 单脚本跑在同一连接上，临时表随会话结束自动消失，不留残留。

CREATE TEMPORARY TABLE tmp_default_tenant (tid BIGINT);

INSERT INTO tmp_default_tenant (tid)
SELECT t.id
FROM sys_tenant t
WHERE t.status = 'ENABLED'
  AND t.deleted_at IS NULL
ORDER BY (
    SELECT COUNT(*)
    FROM org_institution i
    WHERE i.tenant_id = t.id
      AND i.deleted_at IS NULL
) DESC, t.id ASC
LIMIT 1;

UPDATE org_institution i
SET i.tenant_id = (SELECT tid FROM tmp_default_tenant LIMIT 1)
WHERE (i.tenant_id = 0 OR i.tenant_id IS NULL)
  AND i.deleted_at IS NULL;

DROP TEMPORARY TABLE IF EXISTS tmp_default_tenant;
