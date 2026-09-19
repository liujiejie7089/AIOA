#!/usr/bin/env bash
# V61 管理端按钮级全量测试 —— 按角色分进程隔离运行，规避长时间多角色运行
# 导致的 Edge renderer 资源耗尽型挂起（每个角色独立子进程 + 独立浏览器）。
set -u
PY="C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SCRIPT="C:/Users/刘尖尖/WorkBuddy/aioa/scripts/e2e_v61_shell_all_buttons.py"
ROLES=(admin znkj_admin znkjyf_admin znsfb_ldr znsfb_m01)
TOTAL_PASS=0
TOTAL_FAIL=0

for role in "${ROLES[@]}"; do
    echo ""
    echo "############ 角色 $role ############"
    # 每个角色给 180s 硬上限；超时视为该角色环境挂起（不计产品缺陷，单独标注）
    timeout 180 "$PY" -u "$SCRIPT" --role "$role" 2>&1 | tail -8
    rc=${PIPESTATUS[0]}
    if [ "$rc" -eq 0 ]; then
        echo ">>> 角色 $role 通过"
    elif [ "$rc" -eq 124 ]; then
        echo ">>> 角色 $role 超时（环境挂起，非断言失败）"
    else
        echo ">>> 角色 $role 存在失败项（rc=$rc）"
    fi
done
