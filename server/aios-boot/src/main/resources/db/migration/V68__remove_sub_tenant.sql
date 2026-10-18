-- =============================================================================
-- V68 移除「子租户」能力（回退 V66 的租户层级部分）
--
-- 决定（用户，2026-09-28）：目前选择去掉子租户这个功能。
--
-- 范围界定（重要 —— 只回退「子租户」，不回退同一批次的另外两项能力）：
--   ✗ 回退：sys_tenant.parent_id / level（租户层级）+ idx_tenant_parent。
--     这三者只被「租户管理员在本租户下开子租户」这条链路使用；代码侧
--     SubTenantController / SubTenantService 已删除，OrgStatMapper 的子租户查询
--     （selectSubTenants / sumSubTenantPools / countSubTenants / insertTenant / …）同步摘除。
--   ✓ 保留：sys_tenant.domain + uk_tenant_domain ——「租户登录域名」是独立能力，
--     由平台 TenantController 维护，与子租户无依赖关系。
--   ✓ 保留：平台「调整某租户资源上限」（PlatformTenantQuotaController），同样独立。
--
-- 为什么不直接改 V66 而要新加一版：
--   flyway.validate-on-migrate=true，V66 已应用成功；改动其内容会让校验和对不上，
--   下次启动直接 MigrationChecksumMismatchException。迁移只能前进，不能回头改。
--
-- 前置事实（删列前已核对）：sys_tenant 仅 4 行，全部 parent_id=0 / level=1，
--   即**不存在**任何子租户行 —— 删列不会产生「失去层级标识的孤儿租户」。
--   层级列没有数据要搬迁，DROP 是安全的（不需要 SELECT INTO 备份）。
--
-- 兼容性：
--   · 全新库按序执行 V66（加列）→ V68（删列），净效果 = 只有 domain，与存量库一致；
--   · domain / uk_tenant_domain 不在此文件中出现，不会被误删。
-- =============================================================================

-- 先删索引再删列：idx_tenant_parent(parent_id, deleted_at) 若只摘掉 parent_id，
-- 会留下一个只按 deleted_at 建的无用索引 —— 显式删掉，不留半成品。
ALTER TABLE sys_tenant DROP INDEX idx_tenant_parent;

ALTER TABLE sys_tenant DROP COLUMN parent_id;
ALTER TABLE sys_tenant DROP COLUMN level;
