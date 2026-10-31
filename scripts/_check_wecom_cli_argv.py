# -*- coding: utf-8 -*-
"""企微 CLI「参数向量」哨兵 —— 用真 CLI 的 `--help` 当事实源，不需要授权、不联网。

## 为什么要有这个

2026-10-31 生产现场：用户问「我企业微信里有什么未读消息」，助手回
「调用企业微信邮箱搜索工具时出现了参数错误」，试两次后放弃并建议用户自己去后台看。

真相是 `mail_search` 把布尔开关拼成了带值形式：

    wecom-cli mail search ... --only-unread true
    error: unexpected argument 'true' found

`--only-unread` 在官方 CLI 里是**开关（不带值）**。这个错误有几分成心：
  · 只在 `onlyUnread=true` 时触发 ⇒ 问「未读」必炸，问别的全好；
  · 帮助文本写的是「true-仅未读 false-都返回」，看起来像要传值；
  · 错误被包成工具错误交给模型，模型只能转述成「参数错误」⇒ 看起来像模型不会用工具。

这类 bug **不会在本地报错**（参数拼错是运行期的事），所以必须拿 CLI 自己的 `--help`
当判据。没有 CLI 的机器（如 CI）自动跳过动态项，静态项仍然生效。

## 判据

  R1  `argv.mail_search` 里的全部 flag 都在 CLI help 里，且带值与否**完全一致**
  R2  `onlyUnread=True` 时 `--only-unread` **后面不跟任何值**（本次事故点）
  R3  其余三个构造函数（session_messages / recent_sessions / contact_search）同样校验
  R4  `--keywords` 变参：多关键词展开正确、中文逗号认
  R5  端到端：真 CLI 跑 `--dry-run`，输出里**不得**出现 `unexpected argument`
  C1  负向自检：把 `--only-unread` 改回带 "true"，R2 + R5 必须转红
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "mcp-hub"
sys.path.insert(0, str(HUB))

from mcp_hub.wecom_cli import argv  # noqa: E402

PASS = 0
FAIL = 0
SKIP = 0
FAILS: list[str] = []

BEGIN = "2026-10-24 00:00:00"
END = "2026-10-31 23:59:59"


def ok(n: str, extra: str = "") -> None:
    global PASS
    PASS += 1
    print(f"[OK  ] {n}" + (f" — {extra}" if extra else ""))


def bad(n: str, extra: str = "") -> None:
    global FAIL
    FAIL += 1
    FAILS.append(n + (f" — {extra}" if extra else ""))
    print(f"[FAIL] {n}" + (f" — {extra}" if extra else ""))


def skip(n: str, why: str) -> None:
    global SKIP
    SKIP += 1
    print(f"[SKIP] {n} — {why}")


def chk(cond: bool, n: str, extra: str = "") -> bool:
    (ok if cond else bad)(n, extra)
    return cond


def head(t: str) -> None:
    print(f"\n=== {t} ===")


# ---------------------------------------------------------------------------
def find_cli() -> str | None:
    """定位真 CLI：env → 本机 WorkBuddy 包 → PATH。找不到就跳过动态项。"""
    env = (os.environ.get("AIOS_WECOM_CLI_BIN") or "").strip()
    if env and os.path.isfile(env):
        return env
    pkg = Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages"
    exe = "wecom-cli.exe" if os.name == "nt" else "wecom-cli"
    if (pkg / exe).is_file():
        return str(pkg / exe)
    return shutil.which("wecom-cli")


def help_text(cli: str, cmd: list[str]) -> str:
    p = subprocess.run([cli, *cmd, "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    return (p.stdout or "") + (p.stderr or "")


def flags_of(help_out: str) -> dict[str, bool]:
    """从 help 里解析 {flag: 是否带值}。

    规则：`--x <str>` / `--x [<str>...]` ⇒ 带值；`--x` 后面直接是描述文字 ⇒ 开关。
    只认 `--` 开头的长选项（`-o, --output` 这种会命中 `--output`）。
    """
    out: dict[str, bool] = {}
    for line in help_out.splitlines():
        toks = line.split()
        for i, tok in enumerate(toks):
            if not tok.startswith("--"):
                continue
            flag = tok.split("=")[0].rstrip(",")
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            out[flag] = nxt.startswith("<") or nxt.startswith("[<")
    return out


def validate(name: str, vec: list[str], table: dict[str, bool]) -> None:
    problems = argv.flag_violations(vec, table)
    chk(not problems, f"{name} 的 flag 与 CLI help 完全一致",
        "; ".join(problems[:3]) if problems else f"{len([t for t in vec if t.startswith('--')])} 个 flag")


def main() -> int:
    cli = find_cli()

    # ------------------------------------------------------------------ R2
    head("R2 onlyUnread=True 时 --only-unread 不带值（本次事故点）")
    vec = argv.mail_search(BEGIN, END, keywords="", limit=10, only_unread=True)
    idx = vec.index("--only-unread") if "--only-unread" in vec else -1
    chk(idx >= 0, "R2 mail_search(onlyUnread=True) 里有 --only-unread", str(vec))
    if idx >= 0:
        nxt = vec[idx + 1] if idx + 1 < len(vec) else None
        chk(nxt is None or nxt.startswith("--"),
            "R2 --only-unread 后面不跟值（布尔开关）", f"后面是 {nxt!r}")
    chk("--only-unread" in argv.BOOLEAN_FLAGS,
        "R2 --only-unread 已登记为布尔开关", str(sorted(argv.BOOLEAN_FLAGS)))
    chk("true" not in vec, "R2 向量里没有多余的 'true'", str(vec))

    head("R2b onlyUnread=False 时不该出现该 flag")
    vec0 = argv.mail_search(BEGIN, END, only_unread=False)
    chk("--only-unread" not in vec0, "R2b 缺省不带 --only-unread", str(vec0))

    # ------------------------------------------------------------------ R4
    head("R4 --keywords 变参")
    v = argv.mail_search(BEGIN, END, keywords="张三,李四", limit=5, only_unread=False)
    chk(v[v.index("--keywords") + 1: v.index("--keywords") + 3] == ["张三", "李四"],
        "R4 多个关键词逐个展开", str(v))
    v2 = argv.mail_search(BEGIN, END, keywords="张三，李四")
    chk(v2.count("张三") == 1 and "李四" in v2, "R4 中文逗号也认", str(v2[-4:]))
    v3 = argv.mail_search(BEGIN, END, keywords="  ")
    chk("--keywords" not in v3, "R4 全空白关键词不传 --keywords", str(v3))
    chk("30" == argv.mail_search(BEGIN, END, limit=999)[
        argv.mail_search(BEGIN, END, limit=999).index("--limit") + 1],
        "R4 limit 上限被夹到 30")

    # ------------------------------------------------------------------ R1/R3
    head("R1/R3 全部 flag 与 CLI help 一致")
    if not cli:
        for n in ("R1 mail search", "R3 chat messages list", "R3 chat groups list", "R3 contact users search"):
            skip(n, "本机没有 wecom-cli，跳过动态校验（静态项已生效）")
    else:
        ok("定位到 CLI", cli)
        tables = {
            "mail search": flags_of(help_text(cli, ["mail", "search"])),
            "chat messages list": flags_of(help_text(cli, ["chat", "messages", "list"])),
            "chat groups list": flags_of(help_text(cli, ["chat", "groups", "list"])),
            "contact users search": flags_of(help_text(cli, ["contact", "users", "search"])),
        }
        for k, t in tables.items():
            chk(bool(t), f"解析到 {k} 的 flag 表", f"{len(t)} 个")
        chk(tables["mail search"].get("--only-unread") is False,
            "R1 help 明确 --only-unread 是开关（不带值）",
            f"带值={tables['mail search'].get('--only-unread')}")

        validate("R1 mail search（含未读）",
                 argv.mail_search(BEGIN, END, keywords="报表", limit=10, only_unread=True),
                 tables["mail search"])
        validate("R1 mail search（不带未读）",
                 argv.mail_search(BEGIN, END, keywords="报表"), tables["mail search"])
        validate("R3 chat messages list",
                 argv.session_messages("CHATID123", BEGIN, END), tables["chat messages list"])
        validate("R3 chat groups list",
                 argv.recent_sessions(BEGIN, END), tables["chat groups list"])
        validate("R3 contact users search",
                 argv.contact_search("张三,李四"), tables["contact users search"])

        # -------------------------------------------------------------- R5
        head("R5 端到端：真 CLI --dry-run 不得报 unexpected argument")
        p = subprocess.run(
            [cli, *argv.mail_search(BEGIN, END, limit=10, only_unread=True), "--dry-run"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        out = (p.stdout or "") + (p.stderr or "")
        chk("unexpected argument" not in out,
            "R5 CLI 接受了这条参数向量", 
            [ln for ln in out.splitlines() if "unexpected" in ln][:1] or "无 unexpected argument")
        if "Dry Run" in out:
            ok("R5 dry-run 真的构造出请求（说明参数组合完全合法）")

    # ------------------------------------------------------------------ C1
    head("C1 负向自检：改回带值必须转红")
    broken = list(vec)                      # 已有 "--only-unread"
    broken.insert(broken.index("--only-unread") + 1, "true")
    table = {"--begin-time": True, "--end-time": True, "--limit": True,
             "--keywords": True, "--only-unread": False}
    chk(bool(argv.flag_violations(broken, table)),
        "C1 带值版本被 flag_violations 判为错",
        str(argv.flag_violations(broken, table))[:100])
    if cli:
        p = subprocess.run([cli, *broken, "--dry-run"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        out = (p.stdout or "") + (p.stderr or "")
        chk("unexpected argument" in out, "C1 真 CLI 也会拒绝带值版本（判据非恒真）",
            [ln for ln in out.splitlines() if "unexpected" in ln][:1])

    print("\n" + "=" * 60)
    if FAIL:
        print(f"FAILED  {FAIL} 项未通过（PASS {PASS} / SKIP {SKIP}）")
        for f in FAILS:
            print("  · " + f)
        return 1
    print(f"ALL PASS  {PASS} 项" + (f"（跳过 {SKIP}）" if SKIP else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
