-- ============================================================
-- V57 回填：把「Webhook 事件」列里错记的 Gitee 词表改回托管方真实词表
-- ============================================================
--
-- 背景（2026-09-18 真机实测）
--   gitee_project.webhook_events 是**展示字段**：项目详情页把它按逗号拆开，
--   逐个渲染成标签（GiteeProjectDetailView.vue 的 webhookEvents）。
--   但 GiteeRepoTaskHandler.saveWebhook 落库时写死了 Gitee 词表
--   （push,merge_requests,issues,notes），而仓库上真正订阅的是**托管方词表**：
--     Gitee: push, merge_requests, issues, notes
--     Gitea: push, pull_request, pull_request_review, issues, issue_comment,
--            pull_request_review_comment          （见 GiteaProviderClient.hookEvents）
--   于是所有建在 Gitea（含本地桩，桩也是 Gitea 语义）上的项目，详情页都在
--   **明确地说错自己订了什么** —— 用户可以逐条去仓库的 Webhook 设置页核对。
--
--   代码侧已修：saveWebhook 改为由 RepoProviderClient.hookEventNames 按当前托管方
--   取词表，且与建钩子用同一组开关（同源）。本迁移只修历史行。
--
-- 判定条件（两条同时满足，缺一不可）：
--   1) 该行记的正是那套 Gitee 词表（不是别的值，避免误改人工订正过的行）；
--   2) 仓库地址**不在 gitee.com**（在 gitee.com 上的行，Gitee 词表本来就是对的，
--      必须原样保留 —— 只改托管方不是 Gitee 的行）。
--
-- 影响面：本列为展示字段，不参与任何判定逻辑（建钩子用的是配置开关，
--         回调接收侧按事件头精确匹配）。故本次改写不影响回调行为。
-- 幂等：改后的值不再等于 Gitee 词表，重复执行命中 0 行。
-- 注意：下面的目标值必须与 GiteaProviderClient.hookEvents(true,true,true,true)
--       的**顺序与内容**一致（push / pull_request / pull_request_review / issues /
--       issue_comment / pull_request_review_comment）。
-- ============================================================

UPDATE gitee_project
   SET webhook_events = 'push,pull_request,pull_request_review,issues,issue_comment,pull_request_review_comment'
 WHERE webhook_events = 'push,merge_requests,issues,notes'
   AND gitee_html_url IS NOT NULL
   AND gitee_html_url NOT LIKE '%gitee.com%';
