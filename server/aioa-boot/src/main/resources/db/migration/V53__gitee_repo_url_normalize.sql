-- ===========================================================================
-- V53 · 回填 gitee_project 的仓库地址（真站字段口径修正）
-- ===========================================================================
-- 背景（真机实测，非推断）：
--   Gitee 真站的 repos 接口返回
--     html_url  = https://gitee.com/{owner}/{repo}.git   ← **带 .git 后缀**
--     ssh_url   = git@gitee.com:{owner}/{repo}.git
--     https_url = null                                   ← **该字段不存在**
--   而本地桩（scripts/gitee_stub.py）返回的是
--     html_url  = {base}/{owner}/{repo}                  ← 不带后缀
--     https_url = {base}/{owner}/{repo}.git
--
-- 后果（仅真站出现，桩环境永远测不出）：
--   ① 平台的 gitee_html_url 被当**网页基址**用（GiteeContentService 拼
--      + "/blob/" + branch + "/" + path），带 .git 后缀会拼出
--      .../{repo}.git/blob/master/x.md → 404，文件链接全坏。
--   ② https_url 恒为 null → 前端少一个可用的 HTTPS 克隆入口。
--
-- 代码侧已在 GiteeRepoTaskHandler 修正（webUrl 剥后缀 / cloneUrl 三级回落）。
-- 本迁移修**存量行**：快照不回填，坏地址会一直留在库里（V51 已记录该「无刷新路径」缺口）。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V52，故本文件为 V53。
-- ===========================================================================

-- ① 先用**仍带 .git 的** html_url 回填缺失的 https 克隆地址（顺序不可颠倒：
--    第 ② 步会把后缀剥掉，剥完就不再是合法的 HTTPS 克隆地址了）
UPDATE gitee_project
   SET gitee_https_url = gitee_html_url
 WHERE (gitee_https_url IS NULL OR gitee_https_url = '')
   AND gitee_html_url LIKE '%.git';

-- ② 剥掉网页地址结尾的 .git，使其成为可直接打开、可直接拼子路径的网页基址
UPDATE gitee_project
   SET gitee_html_url = LEFT(gitee_html_url, CHAR_LENGTH(gitee_html_url) - 4)
 WHERE gitee_html_url LIKE '%.git';
