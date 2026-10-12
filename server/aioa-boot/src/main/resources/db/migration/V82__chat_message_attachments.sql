-- V82 会话消息附件（对话内上传文档供 AI 参考，不进知识库；docs/46）
--
-- 背景：用户端（H5）在发起对话时把「通用文件上传」拿到的 file id 放进
--       CreateRunRequest.attachments；后端据此把文件解析为纯文本（复用 KbFileParser，
--       零持久化、不进知识库），与本轮 user 消息同一次 insert 落库到本列，并在多轮历史
--       回填时拼回每轮 content，使「重新打开会话后 AI 仍看得到文档」成立。
--
-- ★ 加列零回归纪律（照 V79 的四类证据口径）：
--   1. 语义自洽：attachments IS NULL → 经典会话（无附件），旧数据全部落此档，行为零变化；
--      非空 → [{file_id,name,text,truncated,(error)}]，仅本轮下发 / 历史回填消费，旧读接口忽略即可。
--   2. 无位置式 INSERT：全仓对 chat_message 的写只经 MyBatis-Plus（ChatMessageMapper extends
--      BaseMapper，无 XML、全仓 "INSERT INTO chat_message" 0 命中），按列名映射；新列可空取
--      NULL，既有写路径（不指定本列）不受影响。
--   3. 无 SELECT * 通用映射：实体 chat_message 用 @TableField(autoResultMap) 显式列映射，
--      新增列按名解析，不会因位置错位（glob **/mapper/*.xml 0 命中，ChatMessageMapper 仅 extends
--      BaseMapper）。本列与 citations / toolCalls 同列族（JSON 可空），风格照抄 V1。

ALTER TABLE `chat_message`
    ADD COLUMN `attachments` JSON NULL
        COMMENT '对话内上传文档（不进知识库）解析结果快照 [{file_id,name,text,truncated,(error)}]，供 AI 参考与历史回填';
