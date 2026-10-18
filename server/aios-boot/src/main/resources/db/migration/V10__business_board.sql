-- ============================================================================
-- AIOA V8 —— 客户端小程序原型 V1.2 新增业务域
--   1) biz_kpi       经营数据看板「指标卡」（本月 / 本季）
--   2) biz_kpi_trend 经营数据看板「近 6 个月趋势柱」
--   3) biz_kpi_insight 经营数据看板「AI 解读 + 数据来源」
--   4) agent_worker  数字员工（自动运行 · 定时产出 · 结果进待办与消息）
--   5) user_result   成果沉淀（会话产出存为成果，可继续编辑 / 发起审批）
-- 数据由管理端维护，用户端只读（数字员工与成果允许用户自助创建）。
-- ============================================================================

CREATE TABLE `biz_kpi` (
                           `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                           `tenant_id`     BIGINT       NOT NULL DEFAULT 0,
                           `period`        VARCHAR(16)  NOT NULL DEFAULT 'month' COMMENT 'month=本月 / quarter=本季',
                           `label`         VARCHAR(64)  NOT NULL COMMENT '指标名，如 销售额',
                           `value_text`    VARCHAR(64)  COMMENT '展示值，如 ¥286.4万',
                           `delta_text`    VARCHAR(32)  COMMENT '变化值，如 +12.3%',
                           `up`            TINYINT      NOT NULL DEFAULT 1 COMMENT '1=上涨(绿/红按业务) 0=下降',
                           `compare_label` VARCHAR(16)  NOT NULL DEFAULT '环比' COMMENT '环比 / 同比',
                           `sort_no`       INT          NOT NULL DEFAULT 0,
                           `updated_at`    DATETIME(6),
                           `created_by`    BIGINT,
                           `deleted_at`    DATETIME(6)
) COMMENT '经营数据看板指标卡';

CREATE INDEX `idx_biz_kpi` ON `biz_kpi` (`tenant_id`, `period`, `sort_no`);

CREATE TABLE `biz_kpi_trend` (
                                 `id`          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                 `tenant_id`   BIGINT       NOT NULL DEFAULT 0,
                                 `period`      VARCHAR(16)  NOT NULL DEFAULT 'month',
                                 `point_label` VARCHAR(16)  NOT NULL COMMENT 'X 轴标签，如 4月',
                                 `num_value`   DECIMAL(16,2) NOT NULL DEFAULT 0 COMMENT '数值（万元）',
                                 `hot`         TINYINT      NOT NULL DEFAULT 0 COMMENT '1=当期高亮',
                                 `sort_no`     INT          NOT NULL DEFAULT 0,
                                 `updated_at`  DATETIME(6),
                                 `deleted_at`  DATETIME(6)
) COMMENT '经营数据看板趋势柱';

CREATE INDEX `idx_biz_kpi_trend` ON `biz_kpi_trend` (`tenant_id`, `period`, `sort_no`);

CREATE TABLE `biz_kpi_insight` (
                                   `id`          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                   `tenant_id`   BIGINT       NOT NULL DEFAULT 0,
                                   `period`      VARCHAR(16)  NOT NULL DEFAULT 'month',
                                   `content`     VARCHAR(1024) COMMENT 'AI 解读正文',
                                   `source_text` VARCHAR(256)  COMMENT '数据来源说明',
                                   `updated_at`  DATETIME(6),
                                   `deleted_at`  DATETIME(6)
) COMMENT '经营数据看板 AI 解读';

CREATE UNIQUE INDEX `uk_biz_kpi_insight` ON `biz_kpi_insight` (`tenant_id`, `period`, `deleted_at`);

CREATE TABLE `agent_worker` (
                                `id`            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                `tenant_id`     BIGINT       NOT NULL DEFAULT 0,
                                `name`          VARCHAR(64)  NOT NULL COMMENT '数字员工名称',
                                `icon`          VARCHAR(16)  NOT NULL DEFAULT 'bot' COMMENT '图标键（前端映射，不存 emoji）',
                                `description`   VARCHAR(256) COMMENT '一句话说明',
                                `status`        VARCHAR(32)  NOT NULL DEFAULT '运行中' COMMENT '运行中 / 待命中 / 已停用',
                                `last_output`   VARCHAR(256) COMMENT '最近产出',
                                `schedule_text` VARCHAR(128) COMMENT '运行计划，如 明日 08:00 / 触发式',
                                `enabled`       TINYINT      NOT NULL DEFAULT 1 COMMENT '1=启用 0=停用',
                                `created_by`    BIGINT,
                                `created_at`    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                                `updated_at`    DATETIME(6),
                                `deleted_at`    DATETIME(6)
) COMMENT '数字员工';

CREATE INDEX `idx_agent_worker` ON `agent_worker` (`tenant_id`, `enabled`, `id`);

CREATE TABLE `user_result` (
                               `id`         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                               `tenant_id`  BIGINT       NOT NULL DEFAULT 0,
                               `user_id`    BIGINT       NOT NULL DEFAULT 0 COMMENT '归属用户',
                               `title`      VARCHAR(256) NOT NULL COMMENT '成果标题',
                               `icon`       VARCHAR(16)  NOT NULL DEFAULT 'doc' COMMENT '图标键',
                               `meta`       VARCHAR(256) COMMENT '元信息，如 今日 09:10 · 公文写作 · 待审核',
                               `body`       TEXT         COMMENT '正文',
                               `status`     VARCHAR(32)  NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT / SUBMITTED / APPROVED',
                               `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                               `updated_at` DATETIME(6),
                               `created_by` BIGINT,
                               `deleted_at` DATETIME(6)
) COMMENT '成果沉淀';

CREATE INDEX `idx_user_result` ON `user_result` (`tenant_id`, `user_id`, `id`);

-- ---------------------------- 种子数据（对应原型 V1.2 演示数据） ----------------------------
INSERT INTO `biz_kpi` (`tenant_id`,`period`,`label`,`value_text`,`delta_text`,`up`,`compare_label`,`sort_no`,`created_by`) VALUES
                                                                                                                              (0,'month','销售额','¥286.4万','+12.3%',1,'环比',1,1),
                                                                                                                              (0,'month','新签订单','43 单','+8',1,'环比',2,1),
                                                                                                                              (0,'month','回款率','87.5%','-2.1%',0,'环比',3,1),
                                                                                                                              (0,'month','活跃客户','156 家','+11',1,'环比',4,1),
                                                                                                                              (0,'quarter','销售额','¥742.9万','+9.6%',1,'同比',1,1),
                                                                                                                              (0,'quarter','新签订单','128 单','+15',1,'同比',2,1),
                                                                                                                              (0,'quarter','回款率','85.2%','-1.4%',0,'同比',3,1),
                                                                                                                              (0,'quarter','活跃客户','203 家','+18',1,'同比',4,1);

INSERT INTO `biz_kpi_trend` (`tenant_id`,`period`,`point_label`,`num_value`,`hot`,`sort_no`) VALUES
                                                                                                 (0,'month','4月',48.0,0,1),
                                                                                                 (0,'month','5月',52.0,0,2),
                                                                                                 (0,'month','6月',59.0,0,3),
                                                                                                 (0,'month','7月',55.0,0,4),
                                                                                                 (0,'month','8月',64.0,0,5),
                                                                                                 (0,'month','9月',70.0,1,6);

INSERT INTO `biz_kpi_insight` (`tenant_id`,`period`,`content`,`source_text`) VALUES
    (0,'month','销售额环比 +12.3%，主要由华东区 3 个大单贡献；回款率连续两月下滑，建议关注 2 笔逾期应收（隆基机电 ¥18.6万）。','来源：产品销售明细.xlsx · ERP 同步 · 数字员工「报表员」每日 08:00 自动汇总'),
    (0,'quarter','三季度销售额同比 +9.6%，增长稳健；回款率低于目标值 90%，建议季末集中催收并暂缓对隆基机电的赊销额度。','来源：产品销售明细.xlsx · ERP 同步 · 数字员工「报表员」每日 08:00 自动汇总');

INSERT INTO `agent_worker` (`tenant_id`,`name`,`icon`,`description`,`status`,`last_output`,`schedule_text`,`enabled`,`created_by`) VALUES
    (0,'政策快讯员','megaphone','每日 08:00 汇总新产业政策推送','运行中','09-08 早报 · 3 条','明日 08:00',1,1),
    (0,'请假助手','bell','假勤审批预审与流转','运行中','09-12 预审 1 单 · 建议同意','触发式（有申请即审）',1,1),
    (0,'办文助手','pen','文稿起草、格式校对、行文规范检查','待命中','09-12 生成对接会通知文稿','随时唤起',1,1);

INSERT INTO `user_result` (`tenant_id`,`user_id`,`title`,`icon`,`meta`,`body`,`status`,`created_by`) VALUES
    (0,2,'供需对接会通知.docx','doc','今日 09:10 · 公文写作 · 待审核','关于组织企业参加全市人工智能应用供需对接会的通知（正文已生成，等待审核）','DRAFT',2),
    (0,2,'产品销售数据分析.xlsx','sheet','09-06 · 数据分析 · 已归档','8 月销售数据分析：环比 +12%，华东区贡献 46%','APPROVED',2);
