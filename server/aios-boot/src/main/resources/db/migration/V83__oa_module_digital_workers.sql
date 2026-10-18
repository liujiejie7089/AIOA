-- V83 OA 模块数字人：为《OA系统功能清单》43 个功能模块各建一个数字人。
--
-- 设计口径（与 docs/52 一致）：
--   · 43 个模块数字人的「类型」不是 WorkerRole 的 4 个硬编码角色，而是 worker_type = OA_<MODULE>。
--     加模块 = 加一行数据，不改代码（docs/52 §6.1）。
--   · 每个数字人的 duty(boundary) 写进 description —— 它是 agent 系统提示里
--     「你的职责边界（唯一可回答的范围）」的取值来源（RunService.buildScope → scope.duty），
--     故每条都用「能做什么；不含什么」句式，把反向边界一并写进去。
--   · tenant_id=0 且 is_template=1 的 43 行为平台模板库（此前该库为空，
--     「从模板创建」实际无模板可选，本迁移一并补齐）。
--   · 随后按模板回填到已有租户，使各租户立刻可见；幂等判据 = 同租户同 worker_type 已存在。
--   · run_mode=ON_DEMAND（按需唤起）：不需要执行时刻，也不会被 WorkerScheduler 扫到。
INSERT INTO `agent_worker`
    (`tenant_id`, `name`, `icon`, `description`, `worker_type`, `run_mode`, `schedule_text`,
     `status`, `enabled`, `visible_scope`, `is_template`, `created_by`, `created_at`, `updated_at`)
VALUES
    (0, '公文助手数字人',     'pen',       '公文起草与校核：通知、请示、报告、函、纪要的拟稿、格式与用语校对；不含用印、签发与对外发送。', 'OA_DOC',         'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '档案助手数字人',     'doc',       '档案归档与借阅：按分类与保管期限归集、编目、检索、借阅登记；不含档案销毁审批。',       'OA_ARCHIVE',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '会议助手数字人',     'calendar',  '会议组织：议题与议程编排、参会人与会议室协调、会议通知与纪要整理、决议跟踪；不含会议经费审批。', 'OA_MEETING', 'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '通讯录数字人',       'user',      '通讯录查询：按姓名、部门、岗位检索联系方式与组织归属；不含修改他人资料与导出全量名册。',   'OA_CONTACT',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '工作日志数字人',     'pen',       '工作日志：日报的撰写、补记、汇总与提交提醒；不含考核评分。',                             'OA_WORKLOG',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '工作计划数字人',     'chart',     '工作计划：月度与季度计划的编制、任务拆解、进度更新与偏差提示；不含资源与预算调配。',     'OA_WORKPLAN',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '工作周报数字人',     'sheet',     '工作周报：按周汇总日志与任务产出，生成周报草稿与要点提炼；不含跨部门绩效评价。',         'OA_WEEKLY',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '费用报销数字人',     'bank',      '费用报销：票据要件核对、费用科目与标准匹配、报销单填报与送审跟踪；不含审批放款。',       'OA_EXPENSE',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '出差助手数字人',     'inbox',     '出差办理：出差申请要件、行程与交通住宿安排建议、差旅标准提示、出差报告；不含费用审批。',   'OA_TRAVEL',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '印章助手数字人',     'scale',     '用印办理：用印申请要件核对、印章类型与权限提示、用印登记查询；不含代为审批与实物盖章。',   'OA_SEAL',        'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '项目助手数字人',     'chart',     '项目协同：立项要件、成员与任务分工、里程碑与文档归集、进度风险提示；不含项目经费审批。',   'OA_PROJECT',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '收藏夹数字人',       'inbox',     '收藏夹：常用文档、制度与链接的收藏、分组与检索；不含内容编辑与他人收藏查看。',             'OA_FAVORITE',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '大事记数字人',       'bell',      '大事记：按时间轴记录重大事项、要事摘要与年度汇编；不含对外发布。',                         'OA_MILESTONE',   'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '工作日历数字人',     'calendar',  '工作日历：日程查询、会议与假期安排、日程冲突提示；不含代他人修改日程。',                   'OA_CALENDAR',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '通知公告数字人',     'megaphone', '通知公告：拟稿、受众范围与发布渠道建议、已读情况查询；不含签发与撤稿审批。',               'OA_NOTICE',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '信息发布数字人',     'megaphone', '信息发布：栏目稿件撰写、发布计划与合规用语校对；不含涉密内容审核结论。',                   'OA_PUBLISH',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '工作安排数字人',     'inbox',     '工作安排：任务下达、责任人与时限设定、进度催办与完成确认；不含考核结论。',                 'OA_ASSIGN',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '重要提醒数字人',     'bell',      '重要提醒：时限类事项的提醒规则设置、到点提醒与逾期提示；不含替代人工决策。',               'OA_REMIND',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '用车助手数字人',     'inbox',     '用车办理：用车申请要件、车辆与驾驶员匹配、行程与费用标准提示；不含派车审批。',             'OA_VEHICLE',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '请假助手数字人',     'clock',     '请假办理：假种与证明材料核对、额度与制度匹配、申请单填报与审批进度跟踪；不含代为审批。',   'OA_LEAVE',       'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '考勤管理数字人',     'clock',     '考勤管理：出勤、迟到、加班、外出的查询与异常申诉、考勤规则解释；不含考勤结果审批与薪资核算。', 'OA_ATTENDANCE', 'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '文档管理数字人',     'doc',       '文档管理：目录与权限、版本与共享、全文检索与归档建议；不含涉密定级审批。',                 'OA_DOCMGR',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '党务助手数字人',     'scale',     '党务工作：三会一课与主题党日的计划记录、党员发展与组织关系要件提示；不含党内审批结论。',   'OA_PARTY',       'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '工会工作数字人',     'user',      '工会工作：会员台账、活动组织、福利与慰问事项办理；不含经费审批。',                         'OA_UNION',       'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '待办助手数字人',     'inbox',     '待办中心：待办与已办清单聚合、优先级与超时提示、一键跳转办理；不含代办审批。',             'OA_TODO',        'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '委托管理数字人',     'user',      '委托管理：工作委托的设定、代理范围与有效期、委托期间事项归属说明；不含越权代办审批。',     'OA_DELEGATE',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '门户首页数字人',     'bot',       '门户导航：功能入口与常用应用指引、待办与通知聚合说明、平台使用问答；不含业务数据修改。',   'OA_PORTAL',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '审批中心数字人',     'trophy',    '审批中心：审批流程与节点说明、单据要件核对、审批进度与退回原因查询；不含代为审批。',       'OA_APPROVAL',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '人事管理数字人',     'user',      '人事管理：员工信息、入转调离要件、合同与证明开具指引、人事制度问答；不含薪资与人事决定审批。', 'OA_HR',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '招聘管理数字人',     'user',      '招聘管理：岗位需求发布、简历筛选要点、面试安排与录用流程指引；不含录用决定。',             'OA_RECRUIT',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '培训管理数字人',     'doc',       '培训管理：年度培训计划、课程与讲师安排、报名与学时统计、效果评估问卷；不含培训经费审批。', 'OA_TRAIN',       'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '知识管理数字人',     'doc',       '知识管理：制度与经验的归集编目、知识库检索与引用、沉淀模板建议；不含知识密级审批。',       'OA_KNOWLEDGE',   'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '资产管理数字人',     'bank',      '资产管理：资产台账、领用调拨盘点报废的流程指引与状态查询；不含处置审批。',                 'OA_ASSET',       'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '合同管理数字人',     'scale',     '合同管理：合同起草要点、相对方与条款风险提示、履约节点与收付款跟踪；不含用印与终审。',     'OA_CONTRACT',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '任务督办数字人',     'inbox',     '任务督办：督办事项立项、责任单位与时限、进展报送与预警、办结材料核对；不含问责结论。',     'OA_TASK',        'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '客户管理数字人',     'user',      '客户管理：客户档案、跟进记录、商机与服务工单跟踪、回访提醒；不含报价与合同承诺。',         'OA_CRM',         'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '财务管理数字人',     'bank',      '财务管理：预算执行查询、收支与凭证要件说明、报表口径解释；不含资金支付与账务调整。',       'OA_FINANCE',     'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '采购管理数字人',     'bank',      '采购管理：采购需求要件、方式与限额适用、供应商与比价记录、验收与付款节点；不含定标审批。', 'OA_PURCHASE',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '问卷调查数字人',     'sheet',     '问卷调查：问卷设计、发放范围与回收统计、结果分析报告；不含代替填答与个人信息外泄。',       'OA_SURVEY',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '安全与权限数字人',   'scale',     '安全与权限：账号与角色权限说明、权限申请办理路径、登录与审计日志查询；不含越权授予。',     'OA_SECURITY',    'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '系统集成数字人',     'bot',       '系统集成：接口与单点登录配置说明、数据同步状态与失败重试指引；不含生产密钥查看。',         'OA_INTEGRATION', 'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '数据分析数字人',     'chart',     '数据分析：指标口径解释、多维统计与趋势对比、报表与图表生成；不含对外披露数据。',           'OA_ANALYTICS',   'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6)),
    (0, '移动办公数字人',     'bot',       '移动办公：移动端功能指引、消息与待办同步、离线与网络问题排查；不含后台配置变更。',         'OA_MOBILE',      'ON_DEMAND', '按需唤起', '待命中', 1, 'TENANT', 1, 0, NOW(6), NOW(6));

-- 回填已有租户：以刚写入的模板为唯一数据源，逐租户复制一份（幂等：同租户同类型已存在则跳过）。
INSERT INTO `agent_worker`
    (`tenant_id`, `name`, `icon`, `description`, `worker_type`, `run_mode`, `schedule_text`,
     `status`, `enabled`, `visible_scope`, `is_template`, `created_by`, `created_at`, `updated_at`)
SELECT t.`id`, m.`name`, m.`icon`, m.`description`, m.`worker_type`, m.`run_mode`, m.`schedule_text`,
       '待命中', 1, 'TENANT', 0, 0, NOW(6), NOW(6)
FROM `sys_tenant` t
CROSS JOIN (SELECT `name`, `icon`, `description`, `worker_type`, `run_mode`, `schedule_text`
            FROM `agent_worker`
            WHERE `tenant_id` = 0 AND `is_template` = 1 AND `worker_type` LIKE 'OA%') m
WHERE t.`id` > 0
  AND NOT EXISTS (SELECT 1 FROM `agent_worker` x
                  WHERE x.`tenant_id` = t.`id` AND x.`worker_type` = m.`worker_type`);

CREATE INDEX `idx_agent_worker_type` ON `agent_worker` (`tenant_id`, `worker_type`);
