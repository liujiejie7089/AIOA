-- V79 会话归属项目（需求一：用户端项目上下文与跨项目隔离）
--
-- 背景：用户端（H5）要求「每个项目作为独立上下文且互不影响；后端分配的数字人仅在所属项目内可用」。
-- 现状：chat_conversation 只有 user_id/worker_id，**无项目维度** ⇒ 数字人分配表 pm_project_worker
--       从未被聊天链路消费，「数字人只在所属项目可用」事实上不成立（grep pm_project_worker 在
--       aioa-chat 内结果为空）。本迁移只加一列，把「会话属于哪个项目」落库，作为隔离的锚点。
--
-- 语义（加列零回归的四类证据之一「语义自洽」）：
--   project_id IS NULL  → 非项目会话（经典形态 / 无项目对话坞）。**旧数据全部落在此档，行为零变化。**
--   project_id = X(>0)  → 该项目内的会话；聊天链路据此校验 worker 归属并下发项目上下文。
--
-- 纯增量、可空、不做回填：既不影响既有 INSERT（新列取 NULL），也不泄漏到既有读接口的语义
-- （新增 JSON 字段 projectId，旧消费方忽略即可）。索引供「按项目列会话」使用。
--
-- 与 V71/V73 等一致：utf8mb4 / InnoDB / DATETIME(6)。

ALTER TABLE `chat_conversation`
    ADD COLUMN `project_id` BIGINT NULL
        COMMENT '所属项目ID（NULL=非项目会话）；会话的项目隔离锚点',
    ADD KEY `idx_chat_conv_project` (`tenant_id`, `user_id`, `project_id`);
