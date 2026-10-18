-- ============================================================
-- V58 修正 V56 回填文案：不得把「上一任托管方的原文」显示给当前用户
-- ============================================================
--
-- 问题（V56 的副作用，由界面探针 _check_gitea_ui_provider.py 的 L3 抓出）
--   V56 回填 error_msg 时**照抄了任务队列里的历史原文**。那 4 条失败发生在本平台还是
--   Gitee 接线的时候，原文里带着「Gitee」与 `aioa.gitee.webhook-base-url`：
--     「…IllegalStateException: 未配置 aioa.gitee.webhook-base-url，Gitee 无法回调本机地址…」
--   而现在平台是 **Gitea** 接线，项目**列表页**会直接渲染 error_msg ⇒ 用户看到
--   「Gitee 无法回调本机地址」，一页里同时出现两个托管方。
--   这正是本项目反复出现的那一类缺陷（界面文案写死/沿用错误托管方），
--   V56 把它从「代码」搬到了「数据」里 —— 探针照样抓住，说明探针值钱。
--
--   更进一步：那段原文现在**事实也已过期** —— webhook-base-url 在当前接线里已配置，
--   「未配置…」会让用户去查一个已经不缺的配置项。所以不该只是改个名字，而应改为
--   「与托管方无关、且不冒充当前原因」的说明，把细节指向唯一权威位置（任务队列）。
--
-- 为什么不直接改 V56
--   V56 已应用，改动会破坏 Flyway checksum（项目既有纪律：已应用迁移只追加不修改）。
--
-- 判定条件（content-based，精确命中 V56 写的那批行）
--   V56 的文案 = 前缀 + `t.last_error`，而任务队列存的 last_error 形如
--   `IllegalStateException: <msg>`（见 GiteeTaskService.finish/runOne 的类名前缀）。
--   代码路径产出的文案走 ProviderFailureText.forWebhookStep(e.getMessage(), …)，
--   用的是 **getMessage()**，不带类名前缀 ⇒ 用 `%IllegalStateException:%` 即可把它们分开，
--   不会误改新代码写出的行，也不会误改人工订正过的行。
--
-- 幂等：改写后的文案不再匹配上面的 LIKE，重复执行命中 0 行。
-- ============================================================

UPDATE gitee_project
   SET error_msg = CONCAT(
           '建仓已完成，但「配置 Webhook」这一步没成功，项目因此停在未就绪状态。',
           '当时的具体原因见任务队列中该项目的 Webhook 配置任务；',
           '点「重试建仓」可只重跑这一步。'),
       updated_at = NOW(6)
 WHERE status = 'FAILED'
   AND error_msg LIKE '建仓已完成，但「配置 Webhook」这一步没成功%'
   AND error_msg LIKE '%IllegalStateException:%';
