-- 统一演示口令：tenant 2 的租户管理员 dsj_admin 口令归一化为 User@123
--
-- 背景（用户报障：「输入机构，管理员账号，User@123 很多都登不上去」）：
--   全库 125 个启用账号中，123 个口令为 User@123、平台账号 admin 为 Admin@123，
--   唯独 dsj_admin 是 123456（V1/V24 遗留的早期播种值）。
--   这属**遗留不一致而非有意设计**，证据：
--     1) 其余全部租户侧演示账号（含 t3~t9 的租户/机构管理员）一律 User@123；
--     2) 仓库内 scripts/verify_config_effect.py 早就写死 DEFAULT_PWD="User@123"
--        并调用 login("dsj_admin")，说明约定的默认口令就是 User@123，
--        该脚本因这个孤例一直是坏的（KeyError: 'accessToken'）；
--     3) 管理端登录页演示提示也只对外宣告 User@123。
--   归一化后，租户侧任意管理员账号均可直接用 User@123 登录，
--   登录体验与其余演示账号一致。
--
-- 口径：仅改 dsj_admin 一个账号；平台账号 admin（Admin@123）不动；
--       sys_user 其余字段（昵称/租户/角色）一律不动 —— 只重写 password_hash。
-- 安全性：哈希取自本库中同样使用 User@123 的既有账号（bcrypt $2a$10$，同一编码器），
--        不做明文入库。
UPDATE `sys_user`
SET `password_hash` = '$2a$10$BDnFHEpQYcHOeDHj4xwqS.5yFFEvQcAA5KdsTtMb5TECerOmRrLEG'
WHERE `username` = 'dsj_admin' AND `deleted_at` IS NULL;
