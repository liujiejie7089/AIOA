#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_check_voice_gesture.py —— 语音输入「手势状态机」哨兵（矩阵入口）

为什么要有它
------------
本轮修的缺陷是「点击录音按钮后无法正常结束录音」，根因在纯 JS 状态机（无浏览器即可复跑证明）：
  (1) 旧 bindVoice 的 pointerup 里 `if(Date.now()-pressAt<300){ handsFree=true; ... return; }`
      —— 短按进入**隐藏免提**继续录音，要再点一次才结束（哨兵 S3 抓住的偏离）。
  (2) 旧 bindVoice 的 pointerdown 首行 `if(state.busy) return;` —— 一旦 busy 就进不到「结束」分支，
      录音停不下来（哨兵 S6 抓住的偏离）。
本环境无法真机验证麦克风（需 HTTPS + 设备，docs/47 §0），但**缺陷本体是纯 JS 状态机**，
可以脱离浏览器用桩跑出来 —— 真实断言在 `scripts/_check_voice_gesture.js`（Node）。
本文件是薄壳：矩阵(_run_all_regression.sh)只跑 *.py，故由它调用 Node 引擎并归并退出码。

修正后的手势语义（哨兵要证明的「正确」）
----------------------------------------
  · 纯「按住说话」：pointerdown 开始 → pointerup 结束并发送（免提/短按进免提已删除）。
  · VoiceInput 内 MIN_MS=300；end() 若已开始录音且 now-t0<MIN_MS ⇒ 误触(too-short)不发送，
    并由 bindVoice 用 toast 提示「按住说话…」（断言读 toast 桩，不读 placeholder 文案）。
  · done 回调签名 done(blob, why)，why∈'too-short'|'cancelled'|'no-media'|null。
  · 「结束」优先于 busy：pointerdown 先判 if(isLive()){end();return;} 再判 if(state.busy) return;。

判据不读界面副本（铁律 12）
---------------------------
断言盯的是 **MediaRecorder 是否真的被 start/stop**、**asrTranscribe 被调用几次**、
**拿到的 blob 是不是 null、toast 桩被调了什么**，而不是 placeholder 文案（文案只是提示，不是事实源）。

用法
----
  python scripts/_check_voice_gesture.py            # 常态：源 + 产物 两份都必须 0 失败
  python scripts/_check_voice_gesture.py --selftest # 判别力证明：**修复前版本**(见 PREFIX_REV)必须为红（S3/S6 必红）
退出码 = 失败数（0 才算通过）；前置不满足（找不到 node / 找不到被测文件）以 2 报错，不伪装 PASS。
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "scripts", "_check_voice_gesture.js")
MANAGED_NODE = r"C:/Users/刘尖尖/.workbuddy/binaries/node/versions/22.22.2-2/node.exe"
OLD_DUMP = os.path.join(ROOT, "logs", "_voice_old.html")

# ★ 判别力证明必须对着「确定的修复前版本」，不能对着 HEAD：
#   修复一旦被提交，HEAD 就是**已修好**的版本，同一哨兵在它上面自然全绿，
#   于是 --selftest 会误报「旧版竟然全绿 ⇒ 哨兵没有判别力」——那是假警报，不是真缺陷。
#   故把「修复前版本」钉死成固定提交（曾因此假警报一次，见 2026-10-13）。
PREFIX_REV = "10d26bc"   # = 66f8c24「修复语音「停不下来」」的父提交
PREFIX_PATH = "user-client/_backup_index_pre_oa.html"

def _out(s=""):
    try:
        sys.stdout.write(s + "\n")
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.write((s + "\n").encode(enc, "replace").decode(enc, "replace"))

def find_node():
    cand = [os.environ.get("AIOA_NODE"), MANAGED_NODE, shutil.which("node"), "node"]
    for c in cand:
        if not c:
            continue
        if os.path.sep in c or "/" in c:
            if os.path.isfile(c):
                return c
        else:
            return c
    return None

def run_engine(node, target):
    """返回 (exit_code, 输出文本)。exit_code 即失败用例数。"""
    p = subprocess.run([node, ENGINE, target], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")

def selftest(node):
    """判别力证明：把「修复前版本」dump 出来，同一哨兵必须为红。"""
    _out("[selftest] 取出修复前版本：git show %s:%s" % (PREFIX_REV, PREFIX_PATH))
    os.makedirs(os.path.dirname(OLD_DUMP), exist_ok=True)
    with open(OLD_DUMP, "w", encoding="utf-8", newline="") as f:
        g = subprocess.run(["git", "show", "%s:%s" % (PREFIX_REV, PREFIX_PATH)],
                           cwd=ROOT, stdout=f, stderr=subprocess.PIPE)
    if g.returncode != 0:
        _out("[SKIP] 本仓库取不到 %s:%s（浅克隆 / 历史被改写？）⇒ 判别力证明无法进行，记非 0。"
             % (PREFIX_REV, PREFIX_PATH))
        return 1
    code, out = run_engine(node, os.path.relpath(OLD_DUMP, ROOT))
    _out(out.rstrip())
    if code == 0:
        _out("[FAIL] 旧版竟然全绿 ⇒ 哨兵对「录音停不下来」没有判别力（断言无效，铁律 12）。")
        return 1
    _out("[OK] 旧版失败 %d 项 ⇒ 哨兵确实能抓住旧缺陷（判别力成立）。" % code)
    return 0

def main():
    selftest_mode = "--selftest" in sys.argv

    if not os.path.isfile(ENGINE):
        _out("[FAIL] 断言引擎不存在：%s" % ENGINE)
        return 2
    node = find_node()
    if not node:
        _out("[SKIP] 找不到 node 运行时 ⇒ 前置不满足，记非 0（不伪装 PASS）。")
        return 2

    targets = ["user-client/_backup_index_pre_oa.html", "user-client/index.html"]
    missing = [t for t in targets if not os.path.isfile(os.path.join(ROOT, t))]
    if missing:
        _out("[FAIL] 被测文件缺失：%s" % ", ".join(missing))
        return 2

    _out("哨兵：scripts/_check_voice_gesture.py   node=%s" % node)
    if selftest_mode:
        return selftest(node)

    total = 0
    for t in targets:
        code, out = run_engine(node, t)
        _out(out.rstrip())
        tag = "源" if t.endswith("_backup_index_pre_oa.html") else "产物"
        _out("  -> [%s] %s  失败=%d" % (tag, t, code))
        total += code
    _out("")
    if total == 0:
        _out("[PASS] 源与产物均 0 失败（产品未手改、与源同源）。")
    else:
        _out("[FAIL] 合计失败 %d 项。" % total)
    return total

if __name__ == "__main__":
    sys.exit(main())
