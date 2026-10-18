-- 票务 / 统一调度均为 M1 演示子应用，尚未接入真实业务系统：
-- 置为禁用后 /api/v1/apps 返回空列表，管理端「我的应用」菜单与首页应用卡片自动隐藏。
-- 真实业务系统接入时，将对应行 enabled 置 1 即可，前端无需改动。
UPDATE app_registry SET enabled = 0 WHERE app_code IN ('ticket', 'dispatch');
