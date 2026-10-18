-- V35 登录日志增加「动作」维度：登录 / 登出
--
-- 背景：`sys_login_log` 原本只记录登录尝试（成功 / 失败），退出登录没有任何留痕，
-- 而前端「退出登录」按钮此前调用 `POST /api/v1/auth/logout` 命中不到后端端点 → 404
-- + 401 报错（详见本次修复）。补上端点后，登出事件同样需要落到审计链上。
--
-- 设计取舍：
--   · 用独立的 `action` 列表达事件类型，复用同一张表，而不是为登出单开一张表 ——
--     登录 / 登出是同一条「会话生命周期」审计，放一起才能按 userId + 时间还原一次会话。
--   · 存量行一律默认 'LOGIN'：历史数据全部来自登录路径，语义准确、无需回填猜测。
--   · JWT 是无状态的，服务端不做令牌吊销（登出 = 客户端丢弃令牌）；本列只承担审计留痕职责。

ALTER TABLE `sys_login_log`
    ADD COLUMN `action` VARCHAR(16) NOT NULL DEFAULT 'LOGIN'
        COMMENT '事件类型：LOGIN 登录 / LOGOUT 登出' AFTER `result`;
