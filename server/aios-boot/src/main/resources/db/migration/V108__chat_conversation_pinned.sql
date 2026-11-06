-- V108 会话置顶（用户端「最近」长按菜单）
--
-- 背景：H5「最近」列表按 last_msg_at 倒序，用户没法把自己常用的会话固定在顶部；
-- 长按菜单要做「置顶」，需要一个持久化位（只放前端 localStorage 在换设备后就丢）。
--
-- 语义：
--   pinned = 1  → 该会话在本人的「最近」列表里置顶（多人各自独立，因为是同一行的自己的会话）
--   pinned = 0  → 正常按 last_msg_at 排序（旧数据全部落在此档，行为零变化）
--   pinned_at   → 置顶时刻。同为用户置顶的会话按它倒序（后置顶的在上），
--                 避免「置顶了 5 条之后顺序乱跳」。
--
-- 索引：列表查询是 (tenant_id, user_id, deleted_at) + ORDER BY pinned DESC, last_msg_at DESC。
-- 既有的 idx 已能撑住（单用户会话量级很小），这里只补一个组合索引覆盖新排序键。
--
-- 与既有迁移一致：utf8mb4 / InnoDB / DATETIME(6)；纯增量、非空默认 0、不做回填。

ALTER TABLE `chat_conversation`
    ADD COLUMN `pinned` TINYINT NOT NULL DEFAULT 0
        COMMENT '1=置顶（在本人的最近列表里固定在最上方）',
    ADD COLUMN `pinned_at` DATETIME(6) NULL
        COMMENT '置顶时刻；多条置顶之间按它倒序',
    ADD COLUMN `title_source` VARCHAR(16) NOT NULL DEFAULT 'AUTO'
        COMMENT '标题来源：AUTO=由用户第一句问题自动总结 / CREATE=创建方指定 / MANUAL=用户手动重命名',
    ADD KEY `idx_chat_conv_pinned` (`tenant_id`, `user_id`, `pinned`, `last_msg_at`);

-- title_source 的用处（「标题写成用户的问题总结」）：
--   首轮对话时，只要标题不是用户手动改过的（MANUAL），就用这一轮的用户问题重写标题。
--   为什么需要额外一列：脚本/集成方 create 时会传技术名（如 grade-sheet-probe、enum-probe），
--   而用户要看到的是「我问了什么」。只看 title 字符串无法区分「技术名」与「用户改过的名」。
--   旧数据默认 AUTO ⇒ 下次发消息时会被首轮问题覆盖一次，属预期（那正是用户要的语义）。
