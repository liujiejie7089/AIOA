#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIOA · 安全写入 deploy/.env 的口令/密钥（deploy/ops/set-secrets.py）

为什么要有它：手册早期用 `sed -i "s|^KEY=.*|KEY='${P}'|"` 写口令，这条路有两个坑 ——
  ① 口令里只要含分隔符 `|` → `sed: unknown option to 's'`，**整条命令失败、值没写进去**，
     而屏幕上只留一行报错，很容易被忽略（本环境 MySQL/Redis 口令就是这么没写成的）；
  ② 口令里只要含 `&` → sed 会把它展开成「整个匹配到的原文」，**不报错但值被悄悄改坏**。
本脚本改用「按行重写」：不做任何模式替换，只把 `KEY=...` 那一行整体换掉，因此对
`$ | & # ! ' " \\ 空格` 全部安全。

用法（在部署机 /opt/aioa 下跑）：
    python3 deploy/ops/set-secrets.py --check                 # 只体检，不改
    python3 deploy/ops/set-secrets.py                         # 交互式逐项输入（不回显）
    python3 deploy/ops/set-secrets.py --only mysql,redis      # 只改指定的几项
    python3 deploy/ops/set-secrets.py --from-env              # 从环境变量读（配合 read -rsp）
    python3 deploy/ops/set-secrets.py --file /path/to/.env    # 指定目标文件

--from-env 用法示例（口令不进 shell 历史、不进 ps）：
    read -rsp 'MySQL 口令: ' MYSQL_PASSWORD; echo
    read -rsp 'Redis 口令: ' SPRING_REDIS_PASSWORD; echo
    read -rsp 'MiniMax Key: ' MINIMAX_API_KEY; echo
    export MYSQL_PASSWORD SPRING_REDIS_PASSWORD MINIMAX_API_KEY
    python3 deploy/ops/set-secrets.py --only mysql,redis,minimax --from-env
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

# 每项：逻辑名 -> (要写的键列表, 是否必填, 说明)
GROUPS = {
    "mysql": (
        ["MYSQL_PASSWORD", "SPRING_DATASOURCE_PASSWORD"],
        True,
        "MySQL 账号 aioa 的口令（末尾通常是 $ ⇒ 本脚本会自动用单引号保住它）",
    ),
    "redis": (
        ["SPRING_REDIS_PASSWORD"],
        True,
        "Redis 口令（本环境该实例有 requirepass，必填）",
    ),
    "minimax": (
        ["MINIMAX_API_KEY"],
        True,
        "MiniMax API Key（MODEL_DEFAULT=minimax，留空 ⇒ 静默降级回声）",
    ),
}
# 这些键只核对、不要求填（本 compose 不读）
OPTIONAL_KEYS = ["MYSQL_ROOT_PASSWORD", "MYSQL_DATABASE"]


# ----------------------------------------------------------------- .env 读写
def split_comment(raw: str) -> tuple[str, str]:
    """把 `KEY=裸值   # 注释` 拆成 (值部分, 注释部分)。
    只在「# 前面有空白、且值部分没有被引号包起来」时才当注释（与 compose 语义一致）。"""
    body = raw.rstrip("\n").rstrip("\r")
    # 找第一个 ' #'
    for i in range(1, len(body)):
        if body[i] == "#" and body[i - 1] in " \t":
            val = body[:i]
            return val, body[i:]
    return body, ""


def parse_value(raw: str) -> str:
    """从 .env 的「KEY=后半段」里取出实际值（按 compose 语义近似）。"""
    val, _ = split_comment(raw)
    v = val.strip()
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1]                    # 单引号：原样
    if len(v) >= 2 and v[0] == v[-1] == '"':
        inner = v[1:-1]
        return inner.replace("$$", "$").replace('\\"', '"').replace("\\\\", "\\")
    v = v.replace("$$", "$")              # 裸值：compose 会做插值，这里只近似
    return v.strip()


def quote_value(v: str) -> str:
    """按 docker compose 的 .env 规则给出最稳的写法。"""
    if "'" not in v:
        # 单引号 = 完全字面量：$ # 空格 ! | & \\ " 全都不用操心
        return "'" + v + "'"
    # 值里本身有单引号 ⇒ 只能用双引号，并把 $ 与 \ 与 " 转义
    esc = v.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$")
    return '"' + esc + '"'


class EnvFile:
    def __init__(self, path: str):
        self.path = path
        with open(path, "r", encoding="utf-8", newline="") as f:
            self.lines = f.read().splitlines(keepends=True)

    def get(self, key: str) -> str | None:
        pref = key + "="
        for ln in self.lines:
            if ln.startswith(pref):
                return parse_value(ln[len(pref):])
        return None

    def set(self, key: str, value: str) -> None:
        pref = key + "="
        out = []
        hit = 0
        for ln in self.lines:
            if ln.startswith(pref):
                _, comment = split_comment(ln[len(pref):].rstrip("\r\n"))
                tail = ("  " + comment.strip()) if comment.strip() else ""
                # 一律用 LF：文件里含 \r 会被 compose/MySQL 当成口令的一部分 ⇒ 鉴权失败且极难查
                out.append("%s=%s%s\n" % (key, quote_value(value), tail))
                hit += 1
            else:
                out.append(ln)
        if hit == 0:
            raise SystemExit("!! %s 里找不到 %s= 这一行，无法写入" % (self.path, key))
        if hit > 1:
            raise SystemExit("!! %s 里 %s= 出现 %d 次，请先手工去重" % (self.path, key, hit))
        self.lines = out

    def save(self) -> None:
        crlf = sum(1 for ln in self.lines if ln.endswith("\r\n"))
        body = "".join(ln[:-2] + "\n" if ln.endswith("\r\n") else ln for ln in self.lines)
        if not body.endswith("\n"):
            body += "\n"
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(body)
        if crlf:
            print("  （已把 %d 处 CRLF 行尾统一成 LF —— 含 \\r 的值会让口令多一个隐藏字符）" % crlf)


# ----------------------------------------------------------------- 报告
PLACEHOLDER_LEN = {"MYSQL_PASSWORD": 22, "SPRING_DATASOURCE_PASSWORD": 22,
                   "SPRING_REDIS_PASSWORD": 25}


def compose_verify(deploy_dir: str) -> bool | None:
    """以 `docker compose config` 的渲染结果为唯一真值，核对容器真正拿到的值长度。
    为什么不用 `bash source` 自检：值里含单引号时只能写成双引号 + `$$`，
    compose 会把它还原成 `$`，但 **bash 会把 `$$` 当成 PID**，两边结果不同，
    用 bash 自检会得出错误结论。返回 True/False/None(无法执行)。"""
    import shutil
    import subprocess
    import json
    if not shutil.which("docker"):
        print("  (本机无 docker，跳过 compose 渲染核对)")
        return None
    try:
        r = subprocess.run(["docker", "compose", "config", "--format", "json"],
                           cwd=deploy_dir, capture_output=True, text=True, timeout=90)
    except Exception as e:                                    # noqa: BLE001
        print("  !! 执行 docker compose config 失败：%s" % e)
        return None
    if r.returncode != 0:
        print("  ✗ `docker compose config` 报错 ⇒ 说明 .env 语法有问题，必须先把这里修干净：")
        for ln in (r.stderr or "").strip().splitlines()[:12]:
            print("      " + ln)
        return False
    try:
        cfg = json.loads(r.stdout)
    except Exception:                                          # noqa: BLE001
        print("  (compose 配置能解析，但 JSON 输出无法读取，跳过逐项核对)")
        return True

    want = [("server", "MYSQL_PASSWORD"), ("server", "SPRING_DATASOURCE_PASSWORD"),
            ("server", "SPRING_REDIS_PASSWORD"), ("agent", "MINIMAX_API_KEY")]
    ok = True
    for svc, key in want:
        envd = ((cfg.get("services") or {}).get(svc) or {}).get("environment") or {}
        if key not in envd:
            print("  %-28s (服务 %s 未注入此键)" % (key, svc))
            continue
        v = envd[key]
        v = "" if v is None else str(v)
        if v.startswith("CHANGE_ME__"):
            print("  %-28s ✗ 容器将收到占位符 len=%d（服务 %s）" % (key, len(v), svc))
            ok = False
        elif v == "":
            print("  %-28s ✗ 容器将收到空值（服务 %s）" % (key, svc))
            ok = False
        else:
            print("  %-28s ✅ 容器将收到 len=%d（服务 %s）" % (key, len(v), svc))
    return ok


def report(env: EnvFile, title: str) -> bool:
    print("\n" + title)
    print("-" * 74)
    ok = True
    for name, (keys, required, _) in GROUPS.items():
        for k in keys:
            v = env.get(k)
            if v is None:
                print("  %-28s ✗ 文件里没有这个键" % k)
                ok = False
                continue
            n = len(v)
            if v.startswith("CHANGE_ME__"):
                tag = "✗ 仍是占位符（len=%d，占位符本身就是这个长度，别当成已填）" % n
                ok = False
            elif v == "":
                tag = "✗ 空" + ("（此项必填）" if required else "")
                ok = ok and not required
            else:
                tag = "✅ 已填 len=%d" % n
            print("  %-28s %s" % (k, tag))
    for k in OPTIONAL_KEYS:
        v = env.get(k)
        print("  %-28s （本 compose 不读，值=%s）" % (k, "空" if not v else "非空"))
    print("-" * 74)
    return ok


# ----------------------------------------------------------------- main
def main() -> int:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ap = argparse.ArgumentParser(description="安全写入 deploy/.env 的口令/密钥")
    ap.add_argument("--file", default=os.path.join(root, "deploy", ".env"))
    ap.add_argument("--check", action="store_true", help="只体检，不修改")
    ap.add_argument("--only", default="", help="只处理这些项，逗号分隔：mysql,redis,minimax")
    ap.add_argument("--from-env", action="store_true",
                    help="从同名环境变量读取（配合 read -rsp / export）")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print("!! 找不到 %s" % args.file)
        print("   先执行： cp deploy/.env.production deploy/.env")
        return 2

    env = EnvFile(args.file)
    print("目标文件：%s" % args.file)

    if args.check:
        ok = report(env, "【体检】文件里的值")
        cv = compose_verify(os.path.dirname(os.path.abspath(args.file)))
        print("\n【体检】compose 渲染后容器真正会收到的值")
        print("-" * 74)
        if cv is None:
            print("  (跳过)")
        elif cv:
            print("  ✅ 全部就绪")
        else:
            ok = False
            print("  ✗ 上面有项没就绪")
        print("\n注意：**不要用 `bash source .env` 校验含单引号的项** —— "
              "那种值只能写成双引号+`$$`，bash 会把 `$$` 当 PID，结论会错。以本脚本/compose 渲染为准。")
        print("\n结论：%s" % ("全部就绪 ✅" if ok else "尚有未填项 ✗（见上）"))
        return 0 if ok else 1

    todo = [s.strip() for s in args.only.split(",") if s.strip()] or list(GROUPS)
    bad = [t for t in todo if t not in GROUPS]
    if bad:
        print("!! 未知项：%s（可选：%s）" % (",".join(bad), ",".join(GROUPS)))
        return 2

    pending = []
    for name in todo:
        keys, required, tip = GROUPS[name]
        label = "%s（%s）" % (name, keys[0])
        if args.from_env:
            val = env.get(keys[0]) or ""
            # 从环境变量覆盖：优先取已导出的同名变量
            for k in keys:
                if os.environ.get(k):
                    val = os.environ[k]
                    break
            if not val or val.startswith("CHANGE_ME__"):
                print("  跳过 %s：环境里没有可用值" % label)
                continue
            print("  读取 %s：来自环境变量，len=%d" % (label, len(val)))
        else:
            print("\n【%s】%s" % (label, tip))
            print("  直接回车 = 保持现值不改")
            val = getpass.getpass("  请输入（不回显）: ")
            if val == "":
                print("  已跳过")
                continue
            again = getpass.getpass("  再输入一次确认: ")
            if again != val:
                print("  ✗ 两次输入不一致，本项跳过")
                continue
        if "\n" in val or "\r" in val:
            print("  ✗ 值里含换行，已跳过（.env 无法表达）")
            continue
        pending.append((name, keys, val))

    if not pending:
        print("\n没有要写入的项。")
        report(env, "【体检】当前状态")
        return 0

    for _name, keys, val in pending:
        for k in keys:
            env.set(k, val)
    env.save()
    print("\n已写入 %s" % args.file)

    # 回读校验：值必须与输入逐字节一致（长度不一致就是被吃字符了）
    back = EnvFile(args.file)
    ok = True
    print("\n【回读校验】")
    for name, keys, val in pending:
        for k in keys:
            got = back.get(k) or ""
            same = (got == val)
            ok = ok and same
            print("  %-28s 写入 len=%-4d 读回 len=%-4d %s"
                  % (k, len(val), len(got), "✅ 一致" if same else "✗ 不一致！"))
    report(back, "【体检】写入后的状态")
    print("\n【回读校验】compose 渲染后容器真正会收到的值")
    print("-" * 74)
    cv = compose_verify(os.path.dirname(os.path.abspath(args.file)))
    if cv is not None:
        ok = ok and cv
    print("\n结果：%s" % ("全部一致 ✅" if ok else "存在不一致 ✗ —— 请把上面表格发我"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
