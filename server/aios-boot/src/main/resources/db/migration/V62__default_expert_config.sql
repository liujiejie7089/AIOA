-- V62: 默认 AI（用户端未选择任何专家时的兜底）
--   1) 内置一位「通用助手」专家（tenant_id=0，全局模板），承载未选专家时的通用对话；
--   2) 新增系统参数 chat.default_expert_key，指定兜底用哪个 ai_expert.expert_key。
--
-- 为什么兜底对象要落库、而不能写死在前端：
--   - 「内置一个默认 AI」意味着它必须可被管理端替换（换成业务专线专家等），
--     所以兜底对象是**配置**（sys_config）而不是常量；
--   - 取值为 expert_key，管理端「专家配置」页可一键「设为默认 AI」；
--   - 留空 / 指向不存在的 key ⇒ 后端不标记、用户端降级为本地通用会话，**不报错**。
--
-- 为什么通用助手的 sort=0：它是「未选任何功能时」的默认去处，排在目录最前与默认标记一致，
-- 用户端 `experts[0]` 的历史兜底口径也因此天然落在它身上。
--
-- 与 AdminConfigController.BUILTIN_DEFAULTS 的关系：该键必须同步进内置兜底表，
-- 否则「平台默认表为空」的环境（sys_config 一行都没有）读不到该参数，
-- 管理端会抛「参数不存在」。

-- 1) 通用助手（全局模板） ----------------------------------------------------
-- 幂等：uk_ai_expert(tenant_id, expert_key) 命中则只把「可用性」拉回正轨，
-- 不覆盖历史环境里管理员可能已调整过的文案。
INSERT INTO `ai_expert`
    (`tenant_id`, `expert_key`, `name`, `icon`, `summary`, `intro`, `tags`, `recs`,
     `agent_code`, `enabled`, `sort`, `audit_status`)
VALUES
    (0, 'general', '通用助手', 'bot',
     '日常办公通用问答；涉及具体业务时，我会帮你找到对应专家或建一个数字员工',
     '我是平台内置的通用助手，不限定领域的问题可以直接问我。如果问题涉及审批、办文、法务、政策申报、数据分析等具体业务，我会提示你转到对应的专家 AI，或帮你创建一个专属数字员工。',
     JSON_ARRAY('通用问答', '日常办公'),
     JSON_ARRAY('帮我起草一份会议通知', '这段工作总结怎么改得更精炼？', '公司要采购一批设备，我该走什么流程？'),
     'main', 1, 0, 'APPROVED')
ON DUPLICATE KEY UPDATE `enabled` = 1;

-- 2) 参数键：默认 AI ---------------------------------------------------------
-- 只为「已经有参数行的租户」补行（含平台默认租户 0）：
--   · 一行都没有的租户走 loadTenantConfigs 的克隆路径，会从内置兜底表整份初始化（已含本键）；
--   · 已有行的租户不会被再次克隆，所以必须由本迁移补。
-- 反过来，若对「一行都没有的租户 0」也插一行，会把它钉死在「非空」状态，
-- 从此再也拿不到其余的出厂参数 —— 这是本迁移刻意规避的坑。
INSERT INTO `sys_config`
    (`tenant_id`, `config_key`, `config_value`, `value_type`, `group_code`, `config_name`,
     `description`, `unit`, `default_value`, `editable`, `sort_no`)
SELECT t.tid, 'chat.default_expert_key', 'general', 'STRING', 'CONVERSATION',
       '默认 AI（未选专家时）',
       '用户端未选择任何专家时的兜底 AI，取值为 ai_expert.expert_key；留空表示不做兜底',
       '', 'general', 1, 45
  FROM (SELECT DISTINCT `tenant_id` AS tid FROM `sys_config`) t
ON DUPLICATE KEY UPDATE `config_key` = `config_key`;
