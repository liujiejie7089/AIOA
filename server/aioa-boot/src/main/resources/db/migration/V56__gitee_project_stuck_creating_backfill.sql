-- ============================================================
-- V56 回填：把历史遗留的「永久卡在 CREATING」项目判为 FAILED
-- ============================================================
--
-- 背景（2026-09-18 真机实测）
--   项目状态机是 CREATING --(建仓 + 配 Webhook 均成功)--> ACTIVE。
--   建仓与配 Webhook 是**两条独立任务**：CREATE_REPO 成功后入队 CONFIGURE_WEBHOOK。
--   但 GiteeRepoTaskHandler 只在建仓失败时回写项目状态（markFailed），
--   配 Webhook 失败时**只把任务判死，项目没有任何终态迁移** —— 于是项目永远停在
--   CREATING：界面显示「创建中」，没有失败提示，而定时校准只处理 ACTIVE 项目，
--   不会有任何后续动作去动它。用户看到的唯一现象是「点了没反应」。
--
--   实测受害数据 4 条（本次修复前产生）：
--     项目 69/77（租户 2）：CONFIGURE_WEBHOOK 失败于「未配置 webhook-base-url」
--     项目 82/83（租户 9）：CONFIGURE_WEBHOOK 失败于「企业令牌解不开（加密密钥被换）」
--
-- 代码侧已修
--   GiteeRepoTaskHandler.configureWebhook 现在与 createRepo 对称：
--   失败即回写项目 FAILED + 可执行文案（ProviderFailureText.forWebhookStep）。
--   本迁移只负责把**已经卡住的历史行**补成同样的终态。
--
-- 判定条件（三选三，缺一不可）—— 必须确保不会误伤「正在创建中」的项目：
--   1) status = 'CREATING' 且未删除；
--   2) 创建已超过 30 分钟（正常一轮建仓 + 配 Webhook 在秒级完成）；
--   3) 该项目**没有任何在途任务**（PENDING / RUNNING）—— 正在排队的项目不能被判死；
--   4) 且确实存在一条 FAILED 的 CONFIGURE_WEBHOOK 任务（有据可依才改状态）。
--
-- 幂等：只命中 status='CREATING'，重复执行时已是 FAILED 的行不会被再次改动，
--       且 gitee 任务与审计日志不做任何删改。
-- ============================================================

UPDATE gitee_project p
   SET p.status = 'FAILED',
       p.error_msg = CONCAT(
           '建仓已完成，但「配置 Webhook」这一步没成功，项目因此停在未就绪状态：',
           LEFT(COALESCE(
               (SELECT t.last_error
                  FROM gitee_task t
                 WHERE t.biz_type = 'PROJECT'
                   AND t.biz_id = p.id
                   AND t.task_type = 'CONFIGURE_WEBHOOK'
                   AND t.status = 'FAILED'
                 ORDER BY t.id DESC
                 LIMIT 1),
               '原因未记录，请到任务队列查看该项目的 Webhook 配置任务'), 200),
           '。按上面的提示处理好之后，点「重试建仓」即可只重跑这一步。'),
       p.updated_at = NOW(6)
 WHERE p.status = 'CREATING'
   AND p.deleted_at IS NULL
   AND p.created_at < NOW(6) - INTERVAL 30 MINUTE
   AND NOT EXISTS (SELECT 1
                     FROM gitee_task t2
                    WHERE t2.biz_type = 'PROJECT'
                      AND t2.biz_id = p.id
                      AND t2.status IN ('PENDING', 'RUNNING'))
   AND EXISTS (SELECT 1
                 FROM gitee_task t3
                WHERE t3.biz_type = 'PROJECT'
                  AND t3.biz_id = p.id
                  AND t3.task_type = 'CONFIGURE_WEBHOOK'
                  AND t3.status = 'FAILED');
