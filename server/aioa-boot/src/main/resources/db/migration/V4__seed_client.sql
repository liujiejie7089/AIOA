-- ============================================================================
-- AIOA V4 用户端种子数据
--   口径与《AIOA客户端小程序交互原型》一致，保证联调时前端/后端展示对齐。
--   词元额度：总额 100,000；已用 13,600；赠送 2,000。
-- ============================================================================

-- 专家（4 位，对应原型首页/专家页） -----------------------------------------
INSERT INTO ai_expert (tenant_id, expert_key, name, icon, summary, intro, tags, recs, agent_code, enabled, sort)
VALUES
    (0, 'policy', '政策咨询专家', '🏛️', '德阳/四川产业政策解读与申报指引',
     '熟悉国省市三级产业扶持政策，可基于你上传的政策文件精准解答。',
     JSON_ARRAY('政策问答', '申报指引'),
     JSON_ARRAY('我市对企业上云有什么补贴？', 'OPC 设备联网改造怎么申报？', '算力券如何申领？'),
     'main', 1, 10),
    (0, 'legal', '法律援助专家', '⚖️', '合同初审、劳动用工、常见法律咨询',
     '可对上传合同做初审并标注风险条款，输出修改建议。',
     JSON_ARRAY('合同', '用工'),
     JSON_ARRAY('帮我审查这份采购合同的风险', '试用期辞退的合规要点？'),
     'main', 1, 20),
    (0, 'startup', '企业开办顾问', '🏢', '开办流程、资质办理、惠企政策一站导引',
     '从核名到税务登记的全流程指引，自动匹配适用惠企政策。',
     JSON_ARRAY('开办', '资质'),
     JSON_ARRAY('注册一家科技公司需要哪些材料？'),
     'main', 1, 30),
    (0, 'doc', '办文助手', '📝', '公文格式、行文规范、文稿润色',
     '按党政机关公文格式国标辅助起草与排版。',
     JSON_ARRAY('公文', '润色'),
     JSON_ARRAY('把这段话改成规范的请示语气'),
     'main', 1, 40);

-- 技能（4 个，含动态表单 schema） -------------------------------------------
INSERT INTO ai_skill (tenant_id, skill_name, icon, est_tokens, fields, expert_key, enabled, sort)
VALUES
    (0, '公文写作', '📄', 1500, JSON_ARRAY(
        JSON_OBJECT('k', 'docType', 'label', '文种', 'type', 'select', 'options', JSON_ARRAY('通知', '请示', '工作报告', '函')),
        JSON_OBJECT('k', 'topic', 'label', '主题与要点', 'type', 'textarea', 'value', '关于组织企业参加全市人工智能应用供需对接会的通知'),
        JSON_OBJECT('k', 'words', 'label', '字数要求', 'type', 'input', 'value', '800 字左右')
     ), NULL, 1, 10),
    (0, '合同初审', '⚖️', 2200, JSON_ARRAY(
        JSON_OBJECT('k', 'party', 'label', '合同相对方', 'type', 'input', 'value', 'XX科技有限公司'),
        JSON_OBJECT('k', 'ctype', 'label', '合同类型', 'type', 'select', 'options', JSON_ARRAY('采购合同', '服务合同', '劳动合同', '租赁合同')),
        JSON_OBJECT('k', 'focus', 'label', '关注要点', 'type', 'textarea', 'value', '付款条件、违约责任、知识产权归属')
     ), 'legal', 1, 20),
    (0, '数据分析', '📊', 2600, JSON_ARRAY(
        JSON_OBJECT('k', 'src', 'label', '数据来源', 'type', 'select', 'options', JSON_ARRAY('产品销售明细.xlsx', '经营月报', '手工录入')),
        JSON_OBJECT('k', 'dim', 'label', '分析维度', 'type', 'textarea', 'value', '按月度、区域、产品线对比销售额与同比增速'),
        JSON_OBJECT('k', 'out', 'label', '输出形式', 'type', 'select', 'options', JSON_ARRAY('结论摘要', '图表+解读', '完整报告'))
     ), NULL, 1, 30),
    (0, '办事指引', '🏛️', 900, JSON_ARRAY(
        JSON_OBJECT('k', 'matter', 'label', '办理事项', 'type', 'input', 'value', '企业开办一件事'),
        JSON_OBJECT('k', 'subject', 'label', '办理主体', 'type', 'select', 'options', JSON_ARRAY('个人', '企业', '个体工商户')),
        JSON_OBJECT('k', 'detail', 'label', '具体情况', 'type', 'textarea', 'value', '首次注册科技公司，需了解材料清单与办理时限')
     ), 'startup', 1, 40);

-- 知识库资料（3 个） --------------------------------------------------------
INSERT INTO kb_document (tenant_id, user_id, doc_name, icon, state, size_bytes)
VALUES
    (0, 0, '2026年产业扶持政策汇编.pdf', '📄', 'OK',   4194304),
    (0, 0, '产品销售明细.xlsx',          '📊', 'OK',    131072),
    (0, 0, '会议纪要0905.docx',          '📝', 'WAIT',   65536);

-- 词元额度（租户共享额度：user_id = 0） --------------------------------------
INSERT INTO tenant_quota (tenant_id, user_id, quota_tokens, used_tokens, free_tokens)
VALUES (0, 0, 100000, 13600, 2000);

-- 词元账本流水（历史 4 笔，对应原型账单页） -----------------------------------
INSERT INTO token_ledger (tenant_id, user_id, run_id, biz_type, biz_title,
                          prompt_tokens, completion_tokens, total_tokens, balance_after, created_at)
VALUES
    -- biz_title 只存「对象名」，时间由前端按 created_at 格式化，避免两处时间打架
    (0, 0, 'seed_1', 'CHAT',    '政策咨询专家', 120, 266, 386,  98214, '2026-09-05 14:20:00'),
    (0, 0, 'seed_2', 'SKILL',   '公文写作技能', 480, 1062, 1542, 96672, '2026-09-05 10:12:00'),
    (0, 0, 'seed_3', 'SKILL',   '数据分析技能', 690, 1514, 2204, 94468, '2026-09-04 16:48:00'),
    (0, 0, 'seed_4', 'CHAT',    '办事指引专家', 48,  104,  152,  86316, '2026-09-03 09:30:00');

-- 用户端操作记录（历史 4 条，对应原型「我的操作记录」） ------------------------
INSERT INTO client_activity_log (tenant_id, user_id, action, status, label, created_at)
VALUES
    (0, 0, '发起会话（政策咨询专家）',        'ok', '成功',     '2026-09-05 14:20:00'),
    (0, 0, '上传资料（会议纪要0905.docx）',   'ok', '成功',     '2026-09-05 10:15:00'),
    (0, 0, '购买词元包（10万词元）',          'ok', '已支付',   '2026-09-05 09:58:00'),
    (0, 0, '删除会话（旧手机迁移）',          'ok', '逻辑删除', '2026-09-04 17:02:00');
