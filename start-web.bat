@echo off
chcp 65001 >nul
rem ============================================================
rem AIOS 管理端（web monorepo）启动脚本
rem   shell    :5173   工单 demo-ticket :5174   调度 demo-dispatch :5175
rem 端口分别由 web/apps/*/.env 的 VITE_PORT 决定（.env 被 gitignore，
rem 首次拉取代码后需从 .env.example 复制，否则会落回 vite 默认 5173 互相抢占）。
rem
rem ★ 为什么要单独一个 bat：
rem   由 agent/会话 后台拉起的 dev server 会被外部回收（曾实测存活十几分钟后
rem   凭空消失、日志无异常堆栈）。要长期运行请在**自己的终端**里跑本脚本。
rem ============================================================
setlocal

set "NODE_DIR=D:\Files Other\Node.js"
if exist "%NODE_DIR%\pnpm.cmd" set "PATH=%NODE_DIR%;%PATH%"

cd /d "%~dp0web"

if not exist "node_modules" (
  echo [1/2] 首次运行，安装依赖（约 2 分钟）...
  call pnpm.cmd install --registry https://registry.npmmirror.com
  if errorlevel 1 goto :fail
) else (
  echo [1/2] node_modules 已存在，跳过安装
)

echo [2/2] 启动 dev server（shell :5173 / ticket :5174 / dispatch :5175）...
echo       关闭请在本窗口按 Ctrl+C
call pnpm.cmd -r --parallel dev
goto :eof

:fail
echo.
echo 依赖安装失败，请先确认可访问 npm 镜像，然后重跑本脚本。
pause
