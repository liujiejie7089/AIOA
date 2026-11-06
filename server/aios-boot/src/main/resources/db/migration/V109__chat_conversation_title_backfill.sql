-- V109：把历史会话的标题回填成「用户的问题总结」。
--
-- 背景：V108 引入 title_source 时，给所有存量行都打了默认值 AUTO，但这些行的 title 是
-- 当初创建方传进来的技术名（验收脚本传的 grade-sheet-probe / enum-probe，或数字人入口传的
-- 「请假助手 · 对话」），在用户端「最近」列表里就是一堆看不懂的名字。
--
-- 口径：只动 title_source = 'AUTO' 的行 —— 用户手动改过名的（MANUAL）一律不碰；
-- 有用户消息的，取**首条 user 消息**作为标题（与 RunService#summarizeQuestion 同一语义：
-- 折叠空白 + 超 30 字截断补「…」）。没有用户消息的空会话不在此处理（它们在列表接口里
-- 由 onlyAsked 过滤掉，见 ConversationService#page），标题保持原样以便按 id 打开时仍有显示。
--
-- 与 Java 版的唯一差异：SQL 不做「口语前缀剥离」（帮我看看/请问…）。存量行保留用户原话更忠实，
-- 新会话的标题走 Java 版会剥前缀。

UPDATE `chat_conversation` c
    JOIN (
        -- 每个会话的首条用户消息（MIN(id) 即最早一条，seq 与 id 同向，用 id 避免 seq 为空的历史脏数据）
        SELECT m.conversation_id,
               TRIM(REGEXP_REPLACE(m.content, '[[:space:]]+', ' ')) AS q
        FROM `chat_message` m
                 JOIN (SELECT conversation_id, MIN(id) AS mid
                       FROM `chat_message`
                       WHERE role = 'user'
                       GROUP BY conversation_id) f ON f.mid = m.id
    ) t ON t.conversation_id = c.id
SET c.title = IF(CHAR_LENGTH(t.q) > 30, CONCAT(LEFT(t.q, 30), '…'), t.q)
WHERE c.title_source = 'AUTO'
  AND c.deleted_at IS NULL
  -- 空内容 / 纯空白不覆盖，避免把标题改成空串
  AND t.q <> '';
