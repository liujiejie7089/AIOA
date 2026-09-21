#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIOA · compose 静态体检（deploy/ops/compose-lint.py）
--------------------------------------------------------------------------------
为什么需要它：开发机/隧道机上**通常没有 docker**（`docker compose config` 跑不了），
而 compose 的三类错误又都是「上机才炸」的：

  1. `depends_on` 指向一个 **profile 门控**的服务 —— 默认 `up` 时该依赖不存在，
     报错 `service "x" is required by "y" but is not enabled`。本仓真实踩过：
     `server.depends_on: minio(healthy)` 而 minio 已归入 `profile: [minio]`。
  2. 服务挂了 `volumes: xxx:/path` 但顶层 `volumes:` 没声明 xxx —— `undefined volume`。
  3. compose 里 `${VAR}` / `${VAR:-default}` 引用了 .env 里**根本没有**的键 ——
     会静默取默认值（本仓踩过：口令键缺失 ⇒ 默认空串 ⇒ 连库失败但报错难读）。

本脚本只读不写、不需要 docker、不需要网络。零依赖（pyyaml 已在托管 venv 内）。

用法：
    python deploy/ops/compose-lint.py                       # 默认查 docker-compose.yml + .env.production
    python deploy/ops/compose-lint.py --env deploy/.env
    python deploy/ops/compose-lint.py --override deploy/docker-compose.backend.yml
退出码：0 = 全部通过（允许有 WARN）；1 = 有 ERROR。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("需要 pyyaml：<venv>/Scripts/pip install pyyaml")

ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")
MERGED_KEYS = ("services", "volumes", "networks")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.infos: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warns.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def dump(self) -> int:
        for m in self.infos:
            print(f"  · {m}")
        for m in self.warns:
            print(f"  ⚠ {m}")
        for m in self.errors:
            print(f"  ✗ {m}")
        print()
        if self.errors:
            print(f"结果：✗ {len(self.errors)} 个错误 / {len(self.warns)} 个警告")
            return 1
        print(f"结果：✅ 通过（{len(self.warns)} 个警告）")
        return 0


def load(path: str, rep: Report) -> dict:
    if not os.path.isfile(path):
        rep.err(f"找不到文件：{path}")
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        rep.err(f"{path} YAML 解析失败：{exc}")
        return {}
    data["__raw__"] = raw
    data["__path__"] = path
    return data


def env_keys(path: str) -> set[str] | None:
    if not os.path.isfile(path):
        return None
    keys: set[str] = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            keys.add(line.split("=", 1)[0].strip())
    return keys


def services_of(doc: dict) -> dict:
    svc = doc.get("services") or {}
    return svc if isinstance(svc, dict) else {}


def profiles_of(spec: dict) -> list[str]:
    p = (spec or {}).get("profiles") or []
    if isinstance(p, str):
        return [p]
    return [str(x) for x in p]


def lint(path: str, env_path: str | None, override_path: str | None, rep: Report) -> None:
    print(f"\n\033[36m===== 体检 {path} =====\033[0m")
    main = load(path, rep)
    if not main:
        return
    ov = load(override_path, rep) if override_path else {}
    if override_path and not ov:
        return

    all_svcs = services_of(main)
    ov_svcs = services_of(ov) if ov else {}

    # ---------- 1) profile 门控 / depends_on ----------
    gated = {n: profiles_of(s) for n, s in all_svcs.items() if profiles_of(s)}
    default_set = sorted(n for n in all_svcs if n not in gated)
    rep.info(f"服务共 {len(all_svcs)} 个；默认 up 会起：{', '.join(default_set) or '(无)'}")
    if gated:
        rep.info("profile 门控（默认不起）：" + "；".join(f"{n} ← {p}" for n, p in sorted(gated.items())))

    for name, spec in all_svcs.items():
        dep = (spec or {}).get("depends_on")
        if not dep:
            continue
        my_profiles = set(gated.get(name, []))
        deps = list(dep.keys()) if isinstance(dep, dict) else list(dep)
        for d in deps:
            if d not in all_svcs:
                rep.err(f"services.{name}.depends_on 指向不存在的服务：{d}")
                continue
            dep_profiles = set(gated.get(d, []))
            # 只有在「依赖的 profile 不被本服务覆盖」时才是真错误：
            #   server(无 profile) → minio(profile=minio)  ⇒ 错（默认 up 起不来）
            #   milvus(profile=milvus) → etcd(profile=milvus) ⇒ 对（同一个 profile 一起起）
            if dep_profiles and not dep_profiles.issubset(my_profiles):
                rep.err(
                    f"services.{name}.depends_on 指向 profile 门控服务 {d}（profiles={sorted(dep_profiles)}）"
                    f" 而 {name} 的 profiles={sorted(my_profiles) or '无'} —— 默认 `up` 会报"
                    f" \"required by … but is not enabled\"。要么给 {name} 也加同样的 profile，"
                    f"要么去掉这条依赖。"
                )

    # ---------- 2) 服务挂的命名卷必须在顶层声明 ----------
    declared = set((main.get("volumes") or {}).keys())
    if ov:
        declared |= set((ov.get("volumes") or {}).keys())
    for src, dname in ((main, path), (ov, override_path)):
        if not src:
            continue
        for name, spec in services_of(src).items():
            for v in (spec or {}).get("volumes") or []:
                if not isinstance(v, str):
                    continue
                left = v.split(":", 1)[0]
                if left.startswith(("/", ".", "~")) or "/" in left or "$" in left:
                    continue  # 宿主路径绑定，不是命名卷
                if left not in declared:
                    rep.err(f"{os.path.basename(dname or '')} services.{name} 挂了未声明的命名卷：{left}")

    # ---------- 3) compose 引用的 env 键必须在 env 文件里存在 ----------
    if env_path:
        keys = env_keys(env_path)
        if keys is None:
            rep.warn(f"env 文件不存在，跳过键核对：{env_path}")
        else:
            for src, dname in ((main, path), (ov, override_path)):
                if not src:
                    continue
                label = os.path.basename(dname or "")
                refs = set(ENV_REF.findall(src.get("__raw__", "")))
                missing = sorted(refs - keys)
                if missing:
                    rep.warn(
                        f"{label} 引用了 {env_path} 里没有的键（会静默取 '${{VAR:-默认}}' 的默认值）："
                        + ", ".join(missing)
                    )
            # 占位符残留：模板里正常；若是真实 .env 则必须先跑 ops/set-secrets.py --check
            with open(env_path, "r", encoding="utf-8") as fh:
                ph = [ln.split("=", 1)[0].strip()
                      for ln in fh
                      if "CHANGE_ME__" in ln and "=" in ln and not ln.strip().startswith("#")]
            if ph:
                rep.info(
                    f"{os.path.basename(env_path)} 仍有 {len(ph)} 处 CHANGE_ME__ 占位"
                    f"（{', '.join(ph[:6])}{' …' if len(ph) > 6 else ''}）"
                    f" —— 模板属正常；若这是真实 .env，先跑 `ops/set-secrets.py --check`"
                )

    # ---------- 4) override 里的服务必须在主文件存在 ----------
    if ov:
        for name in ov_svcs:
            if name not in all_svcs:
                rep.err(f"override {override_path} 里的服务 {name} 在主文件中不存在（会被静默忽略）")
        published = []
        for name, spec in ov_svcs.items():
            for p in (spec or {}).get("ports") or []:
                published.append(f"{name}:{p}")
        rep.info(f"override 追加的宿主端口：{', '.join(published) or '(无)'}")
        started = sorted(set(default_set) & set(ov_svcs) - set(gated))
        if started:
            rep.info(f"叠加后典型启动集合：{' '.join(started)}（up 时按需再缩）")


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    deploy = os.path.dirname(here)
    ap = argparse.ArgumentParser(description="AIOA compose 静态体检（不需要 docker）")
    ap.add_argument("--compose", default=os.path.join(deploy, "docker-compose.yml"))
    ap.add_argument("--override", default=None, help="可选叠加文件，如 docker-compose.backend.yml")
    ap.add_argument("--env", default=os.path.join(deploy, ".env.production"),
                    help="用于核对 ${} 引用的环境文件；默认 .env.production")
    args = ap.parse_args()

    rep = Report()
    lint(args.compose, args.env, args.override, rep)
    return rep.dump()


if __name__ == "__main__":
    sys.exit(main())
