-- 审计哈希链：引入算法版本，支持算法升级时的平滑锚定
--
-- 背景：audit_log.created_at 为 DATETIME(6)（微秒），早期写入代码用 LocalDateTime.now()
--       的 9 位纳秒参与哈希，回读时只剩 6 位微秒，导致该批历史记录的 hash 无法复算，
--       整条链被判为断裂（误报）。
--
-- 处理：新增 hash_algo 标记每行使用的哈希算法。
--       V1 = 历史遗留（纳秒时间戳写入，自哈希不可复算，仅参与链式链接校验）
--       V2 = 当前算法（写入前把时间戳截断到微秒，与 DATETIME(6) 精度一致，可完整复算）
--       存量行一律标 V1（保守），新写入行标 V2。
--       校验时：V2 行做「自哈希 + 链式链接」双重校验；V1 行只做链式链接校验，
--       并把最近一条 V1 行视为新链的信任锚 —— 避免算法升级导致整链误报断裂。
ALTER TABLE audit_log
    ADD COLUMN hash_algo VARCHAR(16) NOT NULL DEFAULT 'V1' COMMENT '哈希算法版本：V1=历史遗留(纳秒时间戳)，V2=微秒截断' AFTER hash;

-- 存量行显式写回 V1（DEFAULT 已生效，此处兜底并便于审计）
UPDATE audit_log SET hash_algo = 'V1' WHERE hash_algo IS NULL OR hash_algo = '';
