-- ============================================================================
-- V78: sys_config「平台模板缺失 + 首次克隆不自愈」双缺陷修复（docs/44 §4）
-- ============================================================================
-- 症状（2026-10-10 生产实测，只读）：GET /api/v1/admin/configs → data.total = 3
--   （CONVERSATION: chat.default_expert_key / QUOTA: billing.package.scenes）
--   而本地演示租户（tenant_id=1）是 14+ 条 ⇒「本地齐全、部署到生产只剩几项」。
--
-- 根因（三层叠加，逐层可核对）：
--   ① V18 的 14 条 INSERT 全部落 tenant_id = 1（示例租户），平台模板 tenant_id = 0 **一条都没播**；
--   ② V33 / V34 各往 tenant_id = 0 插了 1 条 ⇒ 模板被写成「非空、但只有 3 条」的畸形态。
--      注意 V62 的注释**明确警告过**这件事（「若对一行都没有的租户 0 也插一行，
--      会把它钉死在非空状态，从此再也拿不到其余出厂参数」）——V33/V34 没有遵守这条告诫。
--   ③ AdminConfigController.loadTenantConfigs 的
--        `if (!rows.isEmpty()) return rows;`   ← 已有几行就返回，永不补齐缺失基座
--        `if (templates.isEmpty()) ...BUILTIN_DEFAULTS`  ← 只有模板为空才走代码兜底
--      被 ② 写成非空后，代码兜底**永远不触发**。
--   ⇒ 任何 tenant_id ≠ 1 的租户，首次克隆拿到的是「只有 3 条」的模板，此后永远停在 3 条。
--      本地之所以「齐全」，只是因为本地演示租户恰好是 1。
--
-- 本迁移负责【数据面】修复；同批代码改动负责【逻辑面】修复
--   （loadTenantConfigs 改为按 config_key 的**键级并集自愈**）。二者缺一不可：
--   · 本迁移治存量（把已经卡住的租户补回完整参数集）；
--   · 代码自愈治增量（将来任何迁移再往模板加键，所有租户下次读取即自动补齐，
--     不必再为每个新键写一条 backfill 迁移 —— 这正是本次缺陷会复发的地方）。
--
-- 幂等性：两条语句均为 INSERT ... ON DUPLICATE KEY UPDATE（命中唯一键
--   uk_sys_config_key = (tenant_id, config_key) 时做 **no-op**）⇒ 重复执行结果一致，
--   且**不覆盖**管理员已改过的值（只补「缺失的键」）。
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1) 补齐「平台模板」（tenant_id = 0）—— 它是唯一权威模板
--    把 V18 的 14 条基座 + V33/V34/V62 各 1 条，共 17 条，全部落到模板。
--    命中已存在行时 config_key = config_key（纯 no-op）：保留平台档已改过的值，不重置。
--    ※ billing.package.scenes 的 JSON 与 V33 逐字一致；因 no-op，实际以 V33 已写入的为准，
--      此处列出只为让「模板 = 全仓播种键的并集」可被静态核对（docs/44 §4.5-D2）。
-- ----------------------------------------------------------------------------
INSERT INTO `sys_config`
    (`tenant_id`, `config_key`, `config_value`, `value_type`, `group_code`, `config_name`,
     `description`, `unit`, `default_value`, `min_value`, `max_value`, `editable`, `sort_no`)
VALUES
    -- 会话与模型
    (0, 'chat.context_rounds',      '10',   'INT',     'CONVERSATION', '单会话上下文轮数上限', '同一会话保留的上下文轮数，超出后自动摘要压缩（P0 FR-D2）',       '轮',   '10',   1,        100,       1, 10),
    (0, 'chat.first_token_ms',      '2000', 'INT',     'CONVERSATION', '首字延迟目标',         '流式输出端到端首字延迟门禁，超出记为体验不达标（P0 FR-D1）',       '毫秒', '2000', 500,      10000,     1, 20),
    (0, 'chat.max_steps',           '8',    'INT',     'CONVERSATION', '智能体最大推理步数',   '单轮任务主循环最大步数，超出强制收束（架构设计 5）',                '步',   '8',    1,        32,        1, 30),
    (0, 'chat.default_model_route', 'auto', 'STRING',  'CONVERSATION', '默认模型路由',         'auto=平台智能路由；亦可指定已上架模型的 providerKey（P0 FR-D4）',   '',     'auto', NULL,     NULL,      1, 40),
    (0, 'chat.default_expert_key',  'general', 'STRING','CONVERSATION', '默认 AI（未选专家时）','用户端未选择任何专家时的兜底 AI，取值为 ai_expert.expert_key；留空表示不做兜底', '', 'general', NULL, NULL,  1, 45),
    -- 额度与计费
    (0, 'quota.low_balance_percent', '20',  'DECIMAL', 'QUOTA',        '额度低余额提醒阈值',   '剩余额度占比低于该值时卡片变色提醒（P0 FR-G1）',                   '%',    '20',   0,        100,       1, 10),
    (0, 'quota.daily_free_tokens',   '20000','INT',    'QUOTA',        '每人每日免费词元',     '普通用户每日发放的免费词元数，次日零点重置（P0 FR-B2）',            '词元', '20000',0,        10000000,  1, 20),
    (0, 'quota.alert_enabled',       'true', 'BOOL',   'QUOTA',        '额度提醒开关',         '关闭后用户端不再展示低余额变色与提示',                             '',     'true', NULL,     NULL,      1, 30),
    (0, 'billing.package.scenes',
     '[{"icon":"user","title":"个人试用","desc":"想先用起来再决定：日常问答、材料随手处理。","points":["体验词元包 · 10 万词元","购买即到账，无需审批"]},{"icon":"spark","title":"团队协作","desc":"3–10 人小组共享额度：周报整理、会议纪要、材料起草。","points":["团队词元包 · 60 万词元","按项目/人头分摊消耗"]},{"icon":"bank","title":"企业规模化","desc":"全单位推广、多机构统一结算与配额下钻。","points":["企业词元包 · 130 万词元","支持机构与部门额度分发"]}]',
     'JSON', 'QUOTA', '词元包适用场景',
     '用户端「购买词元包」页底部的适用场景卡片；JSON 数组，每项 {icon,title,desc,points[]}，icon 取 sprite 图标名（user/spark/bank 等）',
     '',
     '[{"icon":"user","title":"个人试用","desc":"想先用起来再决定：日常问答、材料随手处理。","points":["体验词元包 · 10 万词元","购买即到账，无需审批"]},{"icon":"spark","title":"团队协作","desc":"3–10 人小组共享额度：周报整理、会议纪要、材料起草。","points":["团队词元包 · 60 万词元","按项目/人头分摊消耗"]},{"icon":"bank","title":"企业规模化","desc":"全单位推广、多机构统一结算与配额下钻。","points":["企业词元包 · 130 万词元","支持机构与部门额度分发"]}]',
     NULL, NULL, 1, 40),
    -- 知识库
    (0, 'kb.max_file_mb',            '50',   'INT',     'KNOWLEDGE',    '单文件上传上限',       '单个知识库/资料文件大小上限（P0 FR-F1）',                          'MB',   '50',   1,        2048,      1, 10),
    (0, 'kb.chunk_size',             '800',  'INT',     'KNOWLEDGE',    '切片长度',             'RAG 入库时单切片的目标字符数',                                     '字符', '800',  100,      4000,      1, 20),
    (0, 'kb.top_k',                  '5',    'INT',     'KNOWLEDGE',    '检索召回条数',         '问答检索时返回的切片条数（引用溯源条目上限）',                     '条',   '5',    1,        20,        1, 30),
    (0, 'kb.citation_required',      'true', 'BOOL',    'KNOWLEDGE',    '强制引用溯源',         '开启后引用知识库的回答必须附来源条目（P0 4.1 来源可追溯）',          '',     'true', NULL,     NULL,      1, 40),
    -- 安全合规
    (0, 'security.content_double_check', 'true','BOOL',  'SECURITY',     '内容双审开关',         '输入与输出均过内容安全审核，命中敏感内容中止应答（P0 FR-H3）',      '',     'true', NULL,     NULL,      1, 10),
    (0, 'security.audit_retention_years','3',  'INT',    'SECURITY',     '留痕保存年限',         '台账与操作留痕最少保存年限，满足深度合成管理规定（P0 4.2）',        '年',   '3',    1,        30,        1, 20),
    (0, 'security.realname_required','true', 'BOOL',    'SECURITY',     '强制实名认证',         '开启后未实名用户不可发起会话（P0 FR-A 实名认证）',                 '',     'true', NULL,     NULL,      1, 30),
    -- 审核
    (0, 'approval.tenant.content',   'true', 'BOOL',    'AUDIT',        '租户内容需上级审核',   '开启后，租户管理员创建的数字员工 / 专家进入待审核，需平台管理员通过后生效；关闭则创建即生效。', '', 'true', NULL, NULL, 1, 50)
ON DUPLICATE KEY UPDATE `config_key` = `config_key`;


-- ----------------------------------------------------------------------------
-- 2) 把模板键幂等回填到「已有参数行的租户」—— 治存量
--    · 只针对 `sys_config` 里已经出现过的 tenant_id（= 曾经读过/写过参数、因而被卡住的租户）；
--      一行都没有的租户不需要回填：它们首次读取时走 clone 路径，模板已由第 1 步补全。
--    · 只补「本租户缺、模板有」的键；已存在的键一律不动（NOT EXISTS + ON DUPLICATE 双保险）。
--    · 新补的键取模板的 default_value（出厂默认），而非模板当前的 config_value —— 与代码
--      loadTenantConfigs 的克隆口径保持一致（default_value 优先）。
-- ----------------------------------------------------------------------------
INSERT INTO `sys_config`
    (`tenant_id`, `config_key`, `config_value`, `value_type`, `group_code`, `config_name`,
     `description`, `unit`, `default_value`, `min_value`, `max_value`, `editable`, `sort_no`)
SELECT t.tid, p.`config_key`, p.`default_value`, p.`value_type`, p.`group_code`, p.`config_name`,
       p.`description`, p.`unit`, p.`default_value`, p.`min_value`, p.`max_value`, p.`editable`, p.`sort_no`
  FROM (SELECT DISTINCT `tenant_id` AS tid FROM `sys_config` WHERE `tenant_id` <> 0) t
  CROSS JOIN `sys_config` p
 WHERE p.`tenant_id` = 0
   AND p.`deleted_at` IS NULL
   AND NOT EXISTS (
       SELECT 1 FROM `sys_config` x
        WHERE x.`tenant_id` = t.tid
          AND x.`config_key` = p.`config_key`)
-- 注意：这里的 ODKU 必须写成「目标表全名限定」。
--   INSERT ... SELECT 里源表也叫 sys_config（别名 p），不加限定的话
--   MySQL 会报 1052「Column 'config_key' in field list is ambiguous」
--   （2026-10-10 实测：V78 初版因此迁移失败、应用启动失败）。
ON DUPLICATE KEY UPDATE `sys_config`.`config_key` = `sys_config`.`config_key`;
