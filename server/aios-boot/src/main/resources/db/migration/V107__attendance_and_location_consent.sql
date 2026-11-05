-- 设备定位调用申请 + 员工打卡（2026-11-05，docs/74）
--
-- 需求原话：「本系统要能调用手机设备定位，数字人可调用接口给员工打卡 —— 先完成定位调用申请，
-- 但必须用户同意。」
--
-- 为什么把「同意」做成一张**表**而不是前端一个确认框：
-- 前端弹窗只是「问了」，服务端没有凭据就无法证明「他同意过」。凡是能凭坐标换出考勤记录
-- 的接口，都必须先拿到一张**属于本人、未过期、未被用过**的授权单 ⇒ 越权与事后补录天然不可达。
-- 前端即使被绕过（改 JS、直接 curl），没有 GRANTED 的授权单也打不了卡。
--
-- 状态机（唯一裁决点在该服务里，不在控制器）：
--   PENDING ──用户点允许──> GRANTED ──打卡落库──> USED
--      │                       │
--      └──用户拒绝──> DENIED    └──超时未用──> EXPIRED
--
-- 为什么不把坐标直接存在 attendance_record 上、省掉这张表：
-- 「申请了但被拒绝」「申请了但没点」同样是审计事实，考勤记录里没有位置放它们；
-- 而拒绝率高说明申请文案/时机有问题，这条线索必须留得下来。

CREATE TABLE IF NOT EXISTS `location_consent` (
  `id`            BIGINT       NOT NULL AUTO_INCREMENT,
  `tenant_id`     BIGINT       NOT NULL DEFAULT 0,
  `user_id`       BIGINT       NOT NULL COMMENT '被申请定位的人（= 打卡人，只能是本人）',
  `token`         VARCHAR(48)  NOT NULL COMMENT '一次性凭据，打卡接口必须原样回传',
  `purpose`       VARCHAR(32)  NOT NULL DEFAULT 'ATTENDANCE' COMMENT '用途：ATTENDANCE 打卡',
  `prompt`        VARCHAR(255) NOT NULL DEFAULT '' COMMENT '给用户看的申请文案（谁申请、做什么、有效期）',
  `status`        VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/GRANTED/USED/DENIED/EXPIRED',
  `origin`        VARCHAR(16)  NOT NULL DEFAULT 'H5' COMMENT '发起方：H5 用户点入口 / AI 数字人调用工具',
  `latitude`      DECIMAL(10,6) NULL COMMENT '仅 GRANTED 后有值',
  `longitude`     DECIMAL(10,6) NULL,
  `accuracy_m`    DECIMAL(8,2)  NULL COMMENT '浏览器上报的定位精度（米）',
  `consent_text`  VARCHAR(255) NULL COMMENT '用户同意时前端展示的那句话（原文留痕）',
  `granted_at`    DATETIME(6)  NULL,
  `denied_at`     DATETIME(6)  NULL,
  `used_at`       DATETIME(6)  NULL,
  `expires_at`    DATETIME(6)  NOT NULL COMMENT '过期后一律按 EXPIRED 处理，服务端不信任前端时钟',
  `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `created_by`    BIGINT       NULL,
  `updated_at`    DATETIME(6)  NULL,
  `updated_by`    BIGINT       NULL,
  `deleted_at`    DATETIME(6)  NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_consent_token` (`token`),
  -- 查「我有没有待处理的申请」是每轮对话后都会发生的一次点查，必须有索引
  KEY `idx_consent_user_status` (`tenant_id`, `user_id`, `status`, `expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='设备定位调用申请（一次性、需用户明确同意）';

CREATE TABLE IF NOT EXISTS `attendance_record` (
  `id`           BIGINT       NOT NULL AUTO_INCREMENT,
  `tenant_id`    BIGINT       NOT NULL DEFAULT 0,
  `user_id`      BIGINT       NOT NULL,
  `work_date`    DATE         NOT NULL COMMENT '所属考勤日（按服务器时区取日期，不按客户端）',
  `clock_type`   VARCHAR(8)   NOT NULL COMMENT 'ON 上班 / OFF 下班',
  `clocked_at`   DATETIME(6)  NOT NULL COMMENT '打卡瞬间（服务器时间）',
  `latitude`     DECIMAL(10,6) NULL,
  `longitude`    DECIMAL(10,6) NULL,
  `accuracy_m`   DECIMAL(8,2)  NULL,
  `place_name`   VARCHAR(128) NULL COMMENT '可选：反查到的地点名（本期由前端/模型给，未给则空）',
  `source`       VARCHAR(16)  NOT NULL DEFAULT 'H5' COMMENT 'H5 页面打卡 / AI 数字人代打卡',
  `consent_id`   BIGINT       NULL COMMENT '依据哪张定位授权单，NULL = 管理员补录',
  `remark`       VARCHAR(255) NULL,
  `created_at`   DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `created_by`   BIGINT       NULL,
  `updated_at`   DATETIME(6)  NULL,
  `updated_by`   BIGINT       NULL,
  `deleted_at`   DATETIME(6)  NULL,
  PRIMARY KEY (`id`),
  -- 一天一种类型只留一条：重复点打卡走「返回已有记录」而不是插第二条，
  -- 否则「我早上打了几次卡」这类问题会一天一个答案。带 deleted_at 是为了软删后能重打。
  UNIQUE KEY `uk_attendance_day` (`tenant_id`, `user_id`, `work_date`, `clock_type`, `deleted_at`),
  KEY `idx_attendance_user_date` (`tenant_id`, `user_id`, `work_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='员工打卡记录（含定位与授权依据）';
