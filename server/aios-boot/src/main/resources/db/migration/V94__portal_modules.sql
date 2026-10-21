-- ============================================================================
-- AIOA V94 · 管理端首页门户模块（公告 / 会议 / 日程）
--   对齐 OA 工作台设计稿：管理端首页展示「公告」「会议」「日程」三类卡片。
--
--   表：
--     portal_announcement      —— 公告（平台 tenant_id=0 公共 + 各租户自有）
--     portal_meeting           —— 会议（含组织者）
--     portal_meeting_attendee  —— 会议参会人（邀请状态）
--     portal_schedule          —— 个人日程（属主 user_id）
--
--   隔离口径（与业务一致）：普通登录用户可见「本租户 + tenant_id=0 公共」数据；
--   公告仅出 PUBLISHED，会议按 organizer_id / attendee 区分 mine|invited，
--   日程按 user_id 属主查询。
--
--   手动执行说明：后端运行期间 Flyway 不会重跑，需用 pymysql 直连执行本文件，
--   再补登 flyway_schema_history（installed_rank=94, version='94',
--   script='V94__portal_modules.sql', checksum=NULL, installed_by='manual-apply-20261019',
--   success=1）。所有种子 INSERT 均带 WHERE NOT EXISTS 幂等，可重复执行。
-- ============================================================================

-- ── 1) portal_announcement：公告 ──
CREATE TABLE IF NOT EXISTS `portal_announcement` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL DEFAULT 0 COMMENT '租户（0=平台公共）',
    `title`         VARCHAR(256) NOT NULL COMMENT '标题',
    `category`      VARCHAR(32)  NOT NULL DEFAULT 'NOTICE' COMMENT 'NOTICE/NEWS/POLICY',
    `content`       TEXT         COMMENT '正文',
    `publisher_name` VARCHAR(128) COMMENT '发布人姓名',
    `publish_at`    DATETIME(6)  COMMENT '发布时间',
    `status`        VARCHAR(32)  NOT NULL DEFAULT 'PUBLISHED' COMMENT 'PUBLISHED/OFFLINE',
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`    DATETIME(6),
    `deleted_at`    DATETIME(6)  COMMENT '逻辑删除',
    CONSTRAINT `uk_portal_announcement` UNIQUE (`tenant_id`, `id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '管理端首页公告';

CREATE INDEX `idx_pa_tenant_publish` ON `portal_announcement` (`tenant_id`, `publish_at`);
CREATE INDEX `idx_pa_tenant_status` ON `portal_announcement` (`tenant_id`, `status`);

-- ── 2) portal_meeting：会议 ──
CREATE TABLE IF NOT EXISTS `portal_meeting` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL DEFAULT 0 COMMENT '租户（0=平台公共）',
    `title`         VARCHAR(256) NOT NULL COMMENT '会议主题',
    `start_at`      DATETIME(6)  COMMENT '开始时间',
    `end_at`        DATETIME(6)  COMMENT '结束时间',
    `location`      VARCHAR(256) COMMENT '地点',
    `organizer_id`  BIGINT       COMMENT '组织者 user_id',
    `organizer_name` VARCHAR(128) COMMENT '组织者姓名',
    `status`        VARCHAR(32)  NOT NULL DEFAULT 'SCHEDULED' COMMENT 'SCHEDULED/CANCELED/FINISHED',
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`    DATETIME(6),
    `deleted_at`    DATETIME(6)  COMMENT '逻辑删除',
    CONSTRAINT `uk_portal_meeting` UNIQUE (`tenant_id`, `id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '管理端首页会议';

CREATE INDEX `idx_pm_tenant_organizer` ON `portal_meeting` (`tenant_id`, `organizer_id`);
CREATE INDEX `idx_pm_tenant_start`     ON `portal_meeting` (`tenant_id`, `start_at`);

-- ── 3) portal_meeting_attendee：会议参会人 ──
CREATE TABLE IF NOT EXISTS `portal_meeting_attendee` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL DEFAULT 0 COMMENT '租户（随会议）',
    `meeting_id`    BIGINT       NOT NULL COMMENT '关联 portal_meeting.id',
    `user_id`       BIGINT       NOT NULL COMMENT '参会人 user_id',
    `invite_status` VARCHAR(32)  NOT NULL DEFAULT 'INVITED' COMMENT 'INVITED/ACCEPTED/DECLINED',
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`    DATETIME(6),
    `deleted_at`    DATETIME(6)  COMMENT '逻辑删除',
    CONSTRAINT `uk_portal_meeting_attendee` UNIQUE (`tenant_id`, `id`),
    CONSTRAINT `uk_portal_attendee_meeting_user` UNIQUE (`meeting_id`, `user_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '会议参会人（邀请状态）';

CREATE INDEX `idx_pma_tenant_user` ON `portal_meeting_attendee` (`tenant_id`, `user_id`);

-- ── 4) portal_schedule：个人日程 ──
CREATE TABLE IF NOT EXISTS `portal_schedule` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`     BIGINT       NOT NULL DEFAULT 0 COMMENT '租户（随属主）',
    `user_id`       BIGINT       NOT NULL COMMENT '属主 user_id',
    `title`         VARCHAR(256) NOT NULL COMMENT '日程标题',
    `start_at`      DATETIME(6)  COMMENT '开始时间',
    `end_at`        DATETIME(6)  COMMENT '结束时间',
    `location`      VARCHAR(256) COMMENT '地点',
    `remark`        VARCHAR(512) COMMENT '备注',
    `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`    DATETIME(6),
    `deleted_at`    DATETIME(6)  COMMENT '逻辑删除',
    CONSTRAINT `uk_portal_schedule` UNIQUE (`tenant_id`, `id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '个人日程（属主）';

CREATE INDEX `idx_ps_tenant_user`   ON `portal_schedule` (`tenant_id`, `user_id`);
CREATE INDEX `idx_ps_tenant_start`  ON `portal_schedule` (`tenant_id`, `user_id`, `start_at`);

-- ============================================================================
-- 5) 种子数据：tenant_id = 0（平台公共）与 tenant_id = 56 各一套
--    公告 3 条 / 会议 2 条 / 日程 3 条（覆盖 2026-10-19 今天与 2026-10-20 明天）
--    参会人：uid=1(ACCEPTED) 与 uid=3481(zhangdd, INVITED) 绑定到每个会议
-- ============================================================================

-- ── 5.1 公告（tenant 0）──
INSERT INTO `portal_announcement` (`tenant_id`, `title`, `category`, `content`, `publisher_name`, `publish_at`, `status`, `created_at`, `updated_at`)
SELECT 0, '关于国庆节放假的通知', 'NOTICE',
       '根据国务院办公厅安排，国庆节放假调休共8天（10月1日至10月8日）。请各部门提前做好工作安排，节假日期间注意安全，值班人员按排班表到岗。',
       '办公室', '2026-10-01 09:00:00', 'PUBLISHED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_announcement` x WHERE x.`tenant_id` = 0 AND x.`title` = '关于国庆节放假的通知');

INSERT INTO `portal_announcement` (`tenant_id`, `title`, `category`, `content`, `publisher_name`, `publish_at`, `status`, `created_at`, `updated_at`)
SELECT 0, '系统升级维护公告', 'NOTICE',
       '平台将于2026年10月12日22:00至次日02:00进行系统升级维护，期间部分功能暂停使用，请提前保存数据。由此带来不便敬请谅解。',
       '信息中心', '2026-10-10 18:00:00', 'PUBLISHED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_announcement` x WHERE x.`tenant_id` = 0 AND x.`title` = '系统升级维护公告');

INSERT INTO `portal_announcement` (`tenant_id`, `title`, `category`, `content`, `publisher_name`, `publish_at`, `status`, `created_at`, `updated_at`)
SELECT 0, '新员工入职培训安排', 'NEWS',
       '本月新员工入职培训定于2026年10月15日14:00在总部三楼培训室举行，请近期入职同事准时参加，携带工牌与笔记本。',
       '人力资源部', '2026-10-15 10:00:00', 'PUBLISHED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_announcement` x WHERE x.`tenant_id` = 0 AND x.`title` = '新员工入职培训安排');

-- ── 5.1 公告（tenant 56）──
INSERT INTO `portal_announcement` (`tenant_id`, `title`, `category`, `content`, `publisher_name`, `publish_at`, `status`, `created_at`, `updated_at`)
SELECT 56, '关于国庆节放假的通知', 'NOTICE',
       '依据集团通知，国庆节放假调休共8天（10月1日至10月8日）。请各科室做好值班与安全工作，节后准时返岗。',
       '综合办', '2026-10-01 09:30:00', 'PUBLISHED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_announcement` x WHERE x.`tenant_id` = 56 AND x.`title` = '关于国庆节放假的通知');

INSERT INTO `portal_announcement` (`tenant_id`, `title`, `category`, `content`, `publisher_name`, `publish_at`, `status`, `created_at`, `updated_at`)
SELECT 56, '系统升级维护公告', 'NOTICE',
       '本单位业务系统将于2026年10月11日晚间升级，请于下班前完成待办提交，避免数据丢失。',
       '信息技术科', '2026-10-09 17:00:00', 'PUBLISHED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_announcement` x WHERE x.`tenant_id` = 56 AND x.`title` = '系统升级维护公告');

INSERT INTO `portal_announcement` (`tenant_id`, `title`, `category`, `content`, `publisher_name`, `publish_at`, `status`, `created_at`, `updated_at`)
SELECT 56, '新员工入职培训安排', 'NEWS',
       '2026年第三季度入职员工培训于10月16日09:30在二楼会议室开展，请新同事提前十分钟签到。',
       '人事科', '2026-10-14 11:00:00', 'PUBLISHED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_announcement` x WHERE x.`tenant_id` = 56 AND x.`title` = '新员工入职培训安排');

-- ── 5.2 会议（tenant 0）：组织者 admin/uid=1 与 zhangdd/uid=3481 ──
INSERT INTO `portal_meeting` (`tenant_id`, `title`, `start_at`, `end_at`, `location`, `organizer_id`, `organizer_name`, `status`, `created_at`, `updated_at`)
SELECT 0, '第四季度经营例会', '2026-10-20 09:30:00', '2026-10-20 11:00:00', '第一会议室', 1, 'admin', 'SCHEDULED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_meeting` x WHERE x.`tenant_id` = 0 AND x.`title` = '第四季度经营例会' AND x.`organizer_id` = 1);

INSERT INTO `portal_meeting` (`tenant_id`, `title`, `start_at`, `end_at`, `location`, `organizer_id`, `organizer_name`, `status`, `created_at`, `updated_at`)
SELECT 0, '新产品需求评审会', '2026-10-22 14:00:00', '2026-10-22 15:30:00', '第二会议室', 3481, 'zhangdd', 'SCHEDULED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_meeting` x WHERE x.`tenant_id` = 0 AND x.`title` = '新产品需求评审会' AND x.`organizer_id` = 3481);

-- ── 5.2 会议（tenant 56）──
INSERT INTO `portal_meeting` (`tenant_id`, `title`, `start_at`, `end_at`, `location`, `organizer_id`, `organizer_name`, `status`, `created_at`, `updated_at`)
SELECT 56, '第四季度经营例会', '2026-10-20 10:00:00', '2026-10-20 11:30:00', '总部三楼大会议室', 1, 'admin', 'SCHEDULED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_meeting` x WHERE x.`tenant_id` = 56 AND x.`title` = '第四季度经营例会' AND x.`organizer_id` = 1);

INSERT INTO `portal_meeting` (`tenant_id`, `title`, `start_at`, `end_at`, `location`, `organizer_id`, `organizer_name`, `status`, `created_at`, `updated_at`)
SELECT 56, '新产品需求评审会', '2026-10-22 15:00:00', '2026-10-22 16:30:00', '总部二楼会议室', 3481, 'zhangdd', 'SCHEDULED', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_meeting` x WHERE x.`tenant_id` = 56 AND x.`title` = '新产品需求评审会' AND x.`organizer_id` = 3481);

-- ── 5.3 日程（tenant 0）：uid=1 两条（含 19/20）、uid=3481 一条（含 19）──
INSERT INTO `portal_schedule` (`tenant_id`, `user_id`, `title`, `start_at`, `end_at`, `location`, `remark`, `created_at`, `updated_at`)
SELECT 0, 1, '晨会与日报同步', '2026-10-19 08:30:00', '2026-10-19 09:00:00', '工位', '每日站会', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_schedule` x WHERE x.`tenant_id` = 0 AND x.`user_id` = 1 AND x.`title` = '晨会与日报同步');

INSERT INTO `portal_schedule` (`tenant_id`, `user_id`, `title`, `start_at`, `end_at`, `location`, `remark`, `created_at`, `updated_at`)
SELECT 0, 1, '项目里程碑评审', '2026-10-20 16:00:00', '2026-10-20 17:00:00', '会议室A', '评审 Q3 交付物', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_schedule` x WHERE x.`tenant_id` = 0 AND x.`user_id` = 1 AND x.`title` = '项目里程碑评审');

INSERT INTO `portal_schedule` (`tenant_id`, `user_id`, `title`, `start_at`, `end_at`, `location`, `remark`, `created_at`, `updated_at`)
SELECT 0, 3481, '客户拜访', '2026-10-19 14:00:00', '2026-10-19 15:00:00', '客户公司', '对接年度续约', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_schedule` x WHERE x.`tenant_id` = 0 AND x.`user_id` = 3481 AND x.`title` = '客户拜访');

-- ── 5.3 日程（tenant 56）──
INSERT INTO `portal_schedule` (`tenant_id`, `user_id`, `title`, `start_at`, `end_at`, `location`, `remark`, `created_at`, `updated_at`)
SELECT 56, 1, '晨会与日报同步', '2026-10-19 08:30:00', '2026-10-19 09:00:00', '工位', '每日站会', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_schedule` x WHERE x.`tenant_id` = 56 AND x.`user_id` = 1 AND x.`title` = '晨会与日报同步');

INSERT INTO `portal_schedule` (`tenant_id`, `user_id`, `title`, `start_at`, `end_at`, `location`, `remark`, `created_at`, `updated_at`)
SELECT 56, 1, '项目里程碑评审', '2026-10-20 16:00:00', '2026-10-20 17:00:00', '会议室A', '评审 Q3 交付物', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_schedule` x WHERE x.`tenant_id` = 56 AND x.`user_id` = 1 AND x.`title` = '项目里程碑评审');

INSERT INTO `portal_schedule` (`tenant_id`, `user_id`, `title`, `start_at`, `end_at`, `location`, `remark`, `created_at`, `updated_at`)
SELECT 56, 3481, '客户拜访', '2026-10-19 14:00:00', '2026-10-19 15:00:00', '客户公司', '对接年度续约', NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `portal_schedule` x WHERE x.`tenant_id` = 56 AND x.`user_id` = 3481 AND x.`title` = '客户拜访');

-- ── 5.4 参会人：每个会议挂载 uid=1(ACCEPTED) 与 uid=3481(INVITED) ──
INSERT INTO `portal_meeting_attendee` (`tenant_id`, `meeting_id`, `user_id`, `invite_status`, `created_at`, `updated_at`)
SELECT m.`tenant_id`, m.`id`, 1, 'ACCEPTED', NOW(6), NOW(6)
FROM `portal_meeting` m
WHERE NOT EXISTS (SELECT 1 FROM `portal_meeting_attendee` a WHERE a.`meeting_id` = m.`id` AND a.`user_id` = 1);

INSERT INTO `portal_meeting_attendee` (`tenant_id`, `meeting_id`, `user_id`, `invite_status`, `created_at`, `updated_at`)
SELECT m.`tenant_id`, m.`id`, 3481, 'INVITED', NOW(6), NOW(6)
FROM `portal_meeting` m
WHERE NOT EXISTS (SELECT 1 FROM `portal_meeting_attendee` a WHERE a.`meeting_id` = m.`id` AND a.`user_id` = 3481);
