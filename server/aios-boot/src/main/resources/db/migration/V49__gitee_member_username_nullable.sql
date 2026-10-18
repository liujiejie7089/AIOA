-- ---------------------------------------------------------------------------
-- V49 · gitee_repo_member.gitee_username 允许为 NULL
-- ---------------------------------------------------------------------------
-- 背景（V48 的缺陷修正）：
--   V48 把 gitee_username 定义为 NOT NULL，代码只好给「尚未绑定 Gitee 的平台成员」
--   塞一个 `user-<id>` 形式的占位登录名。这个占位名会一路传到
--   `PUT /repos/{owner}/{repo}/collaborators/{username}` —— 等于把仓库权限
--   授给一个**在 Gitee 上恰好叫这个名字的真实用户**，或者制造一串 404 重试。
--   两者都不可接受。
--
-- 修正方式：列改为可空，未绑定时写 NULL；同步处理器识别 NULL 后原地打回 PENDING，
--   等成员完成绑定再由定时校准补齐。唯一键 (project_id, gitee_username, alive)
--   在 MySQL 下允许多个 NULL，因此同一项目可以有多个未绑定成员而不会互相冲突。
--
-- 说明：V48 已应用，按本项目纪律**不修改已应用迁移**（checksum 不可变），只追加。
-- ---------------------------------------------------------------------------
ALTER TABLE `gitee_repo_member`
    MODIFY COLUMN `gitee_username` VARCHAR(128) NULL
        COMMENT 'Gitee 登录名（协作者接口的键）；成员尚未绑定 Gitee 时为 NULL';

-- 清理 V48 期间可能已写入的占位值：把它们还原为 NULL，交由校准补齐真实登录名。
-- 只影响形如 `user-<数字>` 的占位行，不会误伤真实 Gitee 登录名。
UPDATE `gitee_repo_member`
SET `gitee_username` = NULL,
    `sync_status`    = 'PENDING',
    `last_error`     = '成员尚未绑定 Gitee 账号，待绑定后自动同步权限'
WHERE `gitee_username` LIKE 'user-%'
  AND `gitee_username` REGEXP '^user-[0-9]+$';
