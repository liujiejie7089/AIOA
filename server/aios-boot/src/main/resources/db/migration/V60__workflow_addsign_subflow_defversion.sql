-- =====================================================================
-- V60 工作流补齐：加签 / 子流程 / 流程模板版本对比
--
-- 背景：V45 交付了「审批人策略族 + 处理模式（single/parallel/grab）+ levels + 知会」，
--       但对照 O2OA 的流程能力，仍缺三项常用能力：
--         ① 加签：审批过程中临时插入一个审批人（前加签 / 后加签）；
--         ② 子流程：某节点派生一张子单据，父节点等子单据出结论；
--         ③ 流程模板版本对比：改过哪些节点、改前改后分别是什么。
--       本迁移只补结构（三列 + 一张版本快照表），不改既有数据语义：
--       三列均为可空，缺省 = 无加签、无子流程，与改造前逐行等价。
-- =====================================================================

-- ---------------------------------------------------------------------
-- ① 加签：加签类型（BEFORE 前加签 / AFTER 后加签）+ 谁加的
--    ② 子流程：本节点派生出的子单据 id
--    两者共用 approval_task，因为它们在语义上都是「这个节点上的附加约束」。
-- ---------------------------------------------------------------------
ALTER TABLE `approval_task`
    ADD COLUMN `add_sign_type` VARCHAR(16) NULL COMMENT '加签类型：BEFORE 前加签 / AFTER 后加签（NULL = 非加签节点）',
    ADD COLUMN `added_by`      BIGINT       NULL COMMENT '发起加签的人',
    ADD COLUMN `sub_order_id`  BIGINT       NULL COMMENT '本节点派生的子流程单据 id（NULL = 未发起子流程）';

CREATE INDEX `idx_approval_task_sub_order` ON `approval_task` (`sub_order_id`);

-- ---------------------------------------------------------------------
-- ② 子流程：子单据回指父单据 / 父节点。
--    回指是必需的 —— 子单据出终态时，引擎要据此找到「该去推进哪个父节点」，
--    否则子流程只能靠人工回头去点，等于没闭环。
-- ---------------------------------------------------------------------
ALTER TABLE `approval_order`
    ADD COLUMN `parent_order_id` BIGINT NULL COMMENT '父单据 id（子流程）',
    ADD COLUMN `parent_task_id`  BIGINT NULL COMMENT '触发本子流程的父节点任务 id';

CREATE INDEX `idx_approval_order_parent` ON `approval_order` (`parent_order_id`);

-- ---------------------------------------------------------------------
-- ③ 流程模板版本快照：每次保存流程定义时留一份，供「版本对比」与回溯。
--
--    为什么不直接在 approval_flow_def 上加 version 列做原地覆盖：
--    原地覆盖只能回答「现在是第几版」，回答不了「上一版长什么样」。
--    而管理员真正需要的恰恰是后者 —— 改坏了要知道改了什么、能不能退回。
-- ---------------------------------------------------------------------
CREATE TABLE `approval_flow_def_version` (
                                             `id`             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                                             `tenant_id`      BIGINT       NOT NULL DEFAULT 0,
                                             `def_id`         BIGINT       NOT NULL COMMENT 'approval_flow_def.id',
                                             `version`        INT          NOT NULL DEFAULT 1,
                                             `biz_type`       VARCHAR(32),
                                             `institution_id` BIGINT       NOT NULL DEFAULT 0,
                                             `name`           VARCHAR(128),
                                             `steps_json`     JSON         NULL,
                                             `status`         VARCHAR(16),
                                             `remark`         VARCHAR(512),
                                             `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                                             `created_by`     BIGINT,
                                             CONSTRAINT `uk_flow_def_version` UNIQUE (`def_id`, `version`)
);

CREATE INDEX `idx_flow_def_version_def` ON `approval_flow_def_version` (`def_id`, `version`);
