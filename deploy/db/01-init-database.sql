-- ============================================================================
-- AIOA 生产库初始化（在目标服务器的 MySQL 上执行一次）
--
-- 执行方式（在 10.0.0.12 上）：
--   docker exec -i mysql mysql -uroot -p < deploy/db/01-init-database.sql
--
-- 这个脚本只做三件事：建库 / 建专用账号 / 授权。
-- **表结构与种子数据不在这里** —— 由后端首次启动时 Flyway 自动执行 V1..V61，
-- 跑完即得到「平台基线 + 两个示例数据集」，无需手工导入任何 SQL 文件。
--
-- 跑完记得把 .env 里的三行改成这里的专用账号：
--   SPRING_DATASOURCE_USERNAME=aioa
--   SPRING_DATASOURCE_PASSWORD=<下面那个密码>
--   MYSQL_USER / MYSQL_PASSWORD 同步
-- ============================================================================

CREATE DATABASE IF NOT EXISTS aioa
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 专用账号：后端不使用 root（root 无建库权限时 createDatabaseIfNotExist 会失效，
-- 所以必须先执行上面的 CREATE DATABASE）
CREATE USER IF NOT EXISTS 'aioa'@'%' IDENTIFIED BY 'CHANGE_ME__aioa_db_password';

GRANT ALL PRIVILEGES ON aioa.* TO 'aioa'@'%';
FLUSH PRIVILEGES;

-- 自检：库应存在且为空（0 张业务表）
SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = 'aioa';

SELECT COUNT(*) AS table_count_before_migration
FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'aioa';
