# -*- coding: utf-8 -*-
"""子进程「收尸」哨兵 —— 纯本地，用 python 自己当假 CLI，不需要真企微 CLI。

## 为什么要有这个

2026-11-01 加固前，`mcp-hub/mcp_hub/wecom_cli/runner.py` 有三处漏：

  ① `wait_for(...)` 超时后只 `proc.kill()`，**没 await `proc.wait()`**
     ⇒ 管道传输层没关闭，每超时一次漏一对 fd；
  ② 没接 `CancelledError`：客户端断开时 FastAPI 会 cancel 协程，
     `wait_for` 抛 `CancelledError` 直接穿透 ⇒ **子进程变孤儿继续跑**
     （企微 CLI 是长驻进程，一次断开漏一个）；
  ③ `auth.py` 里三处 `proc.kill()` 同样没有回收。

容器里 uvicorn 就是 PID 1，没人替你收尾，泄漏只会单调累积。
这类问题**功能测试看不出来**（接口都返回 200、内容都对），只有在
`ls /proc/<pid>/fd | wc -l` 或压测时才现形 —— 所以必须单独钉一个哨兵。

## 判据

  R1  超时：抛 CliError（不是裸 asyncio.TimeoutError），且**子进程已退出**
  R2  取消：cancel 协程后**子进程已退出**（加固前会留着）
  R3  正常完成：返回码/输出解析如常（确认加固没改对的行为）
  R4  失败退出：非 0 退出码转成 CliError，且带出 stderr 摘要
  R5  静态契约：run/run_text 走 `_exec`；`_communicate` 的 finally 里
      **同时**有 kill 与 wait；`auth.py` 不再有裸 `proc.kill()`
  C1  负向自检：把 `_communicate` 的 finally 拆掉后，R2 必须转红
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import asyncio
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "mcp-hub"
sys.path.insert(0, str(HUB))

from mcp_hub.wecom_cli import runner  # noqa: E402

PASS = 0
FAIL = 0
FAILS: list[str] = []


def ok(n: str, extra: str = "") -> None:
    global PASS
    PASS += 1
    print(f"[OK  ] {n}" + (f" — {extra}" if extra else ""))


def bad(n: str, extra: str = "") -> None:
    global FAIL
    FAIL += 1
    FAILS.append(n + (f" — {extra}" if extra else ""))
    print(f"[FAIL] {n}" + (f" — {extra}" if extra else ""))


def chk(cond: bool, n: str, extra: str = "") -> bool:
    (ok if cond else bad)(n, extra)
    return cond


def head(t: str) -> None:
    print(f"\n=== {t} ===")


def pid_alive(pid: int) -> bool:
    """进程是否还活着。POSIX 用 /proc；Windows 下 os.kill(pid, 0) 也能探测。"""
    if os.name == "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    p = Path(f"/proc/{pid}")
    return p.is_dir()


class FakeCli:
    """把 runner 的可执行文件临时换成 python 自己，argv 变成一段 python 代码。"""

    def __init__(self, code: str, env_extra: dict[str, str] | None = None):
        self.argv = [sys.executable, "-c", code]
        self._orig = None
        self._env = env_extra or {}
        self._orig_env = None

    def __enter__(self):
        self._orig = runner.bin_path
        runner.bin_path = lambda: sys.executable
        for k, v in self._env.items():
            self._orig_env = self._orig_env or {}
            self._orig_env[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        runner.bin_path = self._orig
        for k, v in (self._orig_env or {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def spawn_pid(code: str, profile: Path) -> asyncio.subprocess.Process:
    return asyncio.get_event_loop().run_until_complete(
        runner.spawn(["-c", code], profile)
    )


async def t_timeout(profile: Path) -> None:
    """超时：CliError + 子进程已死。"""
    code = "import time; time.sleep(30)"
    started = time.monotonic()
    with FakeCli(code):
        try:
            await runner.run_text(["-c", code], profile, timeout=1.2)
        except runner.CliError as e:
            ok("R1 超时抛 CliError 而非裸 asyncio 异常", str(e)[:60])
        except Exception as e:                                # noqa: BLE001
            bad("R1 超时抛 CliError 而非裸 asyncio 异常", f"{type(e).__name__}: {e}")
        else:
            bad("R1 超时抛 CliError 而非裸 asyncio 异常", "居然没抛")
    cost = time.monotonic() - started
    chk(cost < 8, "R1 超时后立刻返回（不是等子进程自己结束）", f"{cost:.1f}s")


async def t_cancel(profile: Path) -> None:
    """取消：子进程必须死。加固前这里会留一个睡 30 秒的孤儿。"""
    code = "import time; time.sleep(30)"
    pid_box: dict[str, int] = {}
    orig_exec = runner.asyncio.create_subprocess_exec

    async def spy(*a, **kw):
        p = await orig_exec(*a, **kw)
        pid_box["pid"] = p.pid
        return p

    with FakeCli(code):
        asyncio.get_event_loop()
        runner.asyncio.create_subprocess_exec = spy
        try:
            task = asyncio.create_task(runner.run_text(["-c", code], profile, timeout=60))
            await asyncio.sleep(1.0)
            chk("pid" in pid_box, "R2 子进程已起")
            pid = pid_box.get("pid", -1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                ok("R2 取消传播为 CancelledError")
            await asyncio.sleep(0.8)
            chk(pid > 0 and not pid_alive(pid),
                "R2 取消后子进程已退出（无孤儿）", f"pid={pid} alive={pid_alive(pid) if pid > 0 else '?'}")
        finally:
            runner.asyncio.create_subprocess_exec = orig_exec


async def t_ok(profile: Path) -> None:
    """正常完成 + 失败退出。"""
    with FakeCli(""):
        try:
            out = await runner.run_text(["-c", "print('authorized')"], profile, timeout=20)
            chk(out == "authorized", "R3 正常输出原样返回", repr(out))
        except Exception as e:                                # noqa: BLE001
            bad("R3 正常输出原样返回", f"{type(e).__name__}: {e}")

        try:
            got = await runner.run(["-c", "print('{\"ok\": 1}')"], profile, timeout=20)
            chk(got == {"ok": 1}, "R3 JSON 输出被解析", str(got))
        except Exception as e:                                # noqa: BLE001
            bad("R3 JSON 输出被解析", f"{type(e).__name__}: {e}")

        try:
            await runner.run_text(["-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
                                  profile, timeout=20)
        except runner.CliError as e:
            chk("企业微信命令失败" in str(e) and "boom" in str(e),
                "R4 非 0 退出转 CliError 并带出 stderr", str(e)[:70])
        except Exception as e:                                # noqa: BLE001
            bad("R4 非 0 退出转 CliError 并带出 stderr", f"{type(e).__name__}: {e}")
        else:
            bad("R4 非 0 退出转 CliError 并带出 stderr", "居然没抛")


def _comm_body(src: str) -> str:
    return src.split("async def _communicate", 1)[1].split("\nasync def ", 1)[0]


def has_reap_guard(src: str) -> bool:
    """R5 的核心谓词：收口函数里「异常路径也一定 kill + wait」这件事是否成立。

    四个条件缺一不可 —— 这也是 C1 负向自检要打的东西：
      有 finally / 判断还未退出 / 真的 kill / 用 shield 包 wait
    """
    if "async def _communicate" not in src:
        return False
    body = _comm_body(src)
    return (
        "finally:" in body
        and "if proc.returncode is None:" in body
        and "proc.kill()" in body
        and "shield(proc.wait())" in body
    )


def t_static() -> None:
    src = (HUB / "mcp_hub" / "wecom_cli" / "runner.py").read_text(encoding="utf-8")
    auth = (HUB / "mcp_hub" / "wecom_cli" / "auth.py").read_text(encoding="utf-8")

    chk("async def _communicate" in src, "R5 _communicate 存在（收口函数）")
    body = _comm_body(src)
    chk(re.search(r"finally:", body) is not None, "R5 _communicate 有 finally 兜底")
    chk("proc.kill()" in body and "proc.wait()" in body,
        "R5 超时/取消路径同时 kill 与 wait（不是只 kill）")
    chk("shield(proc.wait())" in body,
        "R5 wait 用 shield 包裹（取消态下也能等到回收）")
    chk(has_reap_guard(src), "R5 收尸谓词整体成立")

    for fn in ("async def run(", "async def run_text("):
        seg = src.split(fn, 1)[1].split("\nasync def ", 1)[0]
        chk("_exec(" in seg, f"R5 {fn.strip()} 走 _exec 收口",
            "" if "_exec(" in seg else "仍在函数内自己 create_subprocess_exec")
        chk("create_subprocess_exec" not in seg,
            f"R5 {fn.strip()} 内不再直接起子进程")

    bare = [ln.strip() for ln in auth.splitlines()
            if "proc.kill()" in ln and "_reap" not in ln]
    # auth.py 里唯一允许的 proc.kill() 在 _reap 内部
    chk(len(bare) <= 1, "R5 auth.py 的 kill 已收口到 _reap（至多 _reap 内一处）",
        f"发现 {len(bare)} 处裸 kill：{bare[:3]}")


def c1_negative() -> None:
    """拆掉 finally 兜底后谓词必须为假 ⇒ 证明 R5 不是恒真。

    只做静态复制，不动真文件；同时把 R2（取消后无孤儿）说清为什么可信：
    R2 是动态跑出来的（真的 cancel 一个真子进程），加固前会留活进程。
    """
    src_path = HUB / "mcp_hub" / "wecom_cli" / "runner.py"
    orig = src_path.read_text(encoding="utf-8")
    chk(has_reap_guard(orig), "C1 原始文件谓词为真（R5 通过的前提）")

    broken = orig.replace("    finally:\n        if proc.returncode is None:", "    finally:\n        if False:")
    if broken == orig:
        bad("C1 成功构造「无 finally 兜底」的副本", "替换没命中，判据可能失效")
        return
    ok("C1 成功构造「无 finally 兜底」的副本")
    chk(not has_reap_guard(broken), "C1 拆掉兜底后 R5 谓词转假（判据非恒真）")

    # 再拆一层：保留 finally 但去掉 kill，同样必须转假
    broken2 = orig.replace("                proc.kill()", "                pass")
    chk(not has_reap_guard(broken2), "C1 去掉 kill 后 R5 谓词转假")


async def main_async(profile: Path) -> None:
    head("R1 超时路径")
    await t_timeout(profile)
    head("R2 取消路径（客户端断开的真实场景）")
    await t_cancel(profile)
    head("R3/R4 正常与失败退出（确认没改坏对的行为）")
    await t_ok(profile)


def t_env_validation() -> None:
    """R6：秒数型环境变量写错时必须给「人话 + 改法」，而不是裸 ValueError 栈。"""
    import subprocess

    base = dict(os.environ, PYTHONPATH=str(HUB))

    def run_with(val: str | None):
        env = dict(base)
        if val is None:
            env.pop("AIOS_WECOM_CLI_TIMEOUT", None)
        else:
            env["AIOS_WECOM_CLI_TIMEOUT"] = val
        return subprocess.run(
            [sys.executable, "-c",
             "import mcp_hub.wecom_cli.runner as r; print('TIMEOUT', r.TIMEOUT)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)

    p = run_with("30s")
    tail = (p.stderr or "") + (p.stdout or "")
    chk(p.returncode != 0 and "环境变量 AIOS_WECOM_CLI_TIMEOUT" in tail and "不是数字" in tail,
        "R6 非数字取值 ⇒ 中文原因（不是裸 ValueError）",
        [ln for ln in tail.splitlines() if "AIOS_WECOM_CLI_TIMEOUT" in ln][:1])

    p = run_with("0")
    chk(p.returncode != 0 and "必须大于 0" in ((p.stderr or "") + (p.stdout or "")),
        "R6 0 或负数 ⇒ 明确拒绝")

    p = run_with("45")
    chk(p.returncode == 0 and "TIMEOUT 45.0" in (p.stdout or ""),
        "R6 正常取值照常生效", (p.stdout or "").strip()[-20:])

    p = run_with(None)
    chk(p.returncode == 0 and "TIMEOUT 30.0" in (p.stdout or ""),
        "R6 未设置时用默认 30s", (p.stdout or "").strip()[-20:])


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td) / "t0" / "u1"
        (profile / "personal").mkdir(parents=True, exist_ok=True)
        asyncio.run(main_async(profile))

    head("R5 静态契约")
    t_static()

    head("R6 配置校验（写错 env 的报错质量）")
    t_env_validation()

    head("C1 负向自检")
    c1_negative()

    print("\n" + "=" * 60)
    if FAIL:
        print(f"FAILED  {FAIL} 项未通过（PASS {PASS}）")
        for f in FAILS:
            print("  · " + f)
        return 1
    print(f"ALL PASS  {PASS} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
