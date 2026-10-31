# -*- coding: utf-8 -*-
"""「没有可用的企业微信连接」误诊哨兵 —— 纯本地，不起服务、不连外网。

## 为什么要有这个

2026-10-31 生产现场：用户「连接了企业微信」，对话里却回「当前没有可用的企业微信连接」。

链路是：`bin_path()` → `create_subprocess_exec` → `cli_auth.status()` → REST。
compose 里 `AIOS_WECOM_CLI_BIN` 有默认值 `/opt/wecom-cli/wecom-cli`，
而宿主目录不存在时 Docker 会**静默建一个空目录**再挂进来 ⇒ **路径恒有、文件恒无**。
原实现拿 env 直接 return，于是：

  1. `create_subprocess_exec` 抛裸 `FileNotFoundError`；
  2. `cli_auth.status()` 只 `except CliError` ⇒ 异常穿透 ⇒ REST 面 500；
  3. 即便被兜住，也只会变成 `unauthorized` ⇒ 界面「没有可用的连接」，
     **和「还没扫码」完全无法区分** —— 排障时最耗时的那种错。

## 判据

  R1  env 指向**不存在**的路径 ⇒ `bin_path()` 抛 `CliError`（不是 FileNotFoundError），
      消息里必须带出那个路径与「未找到企微 CLI」。
  R2  `probe()` 在同情形下**不抛**，返回 ok=False + error（供 REST 面直接透出）。
  R3  `cli_auth.status()` 在同情形下返回 `unauthorized` 而不是炸掉
      （保证 REST 200，而不是 500）。
  R4  正向对照：env 指向**真实可执行文件** ⇒ `bin_path()` 返回它、`probe().ok=True`
      （证明 R1/R2 不是「恒抛」的假绿）。
  R5  env 指向存在但**不可执行**的文件 ⇒ 仍抛 CliError（挂进来个只读文件不该蒙混过关）。
  S1  `admin_api._status` 的返回体带 `cli` 键（把「CLI 在不在」透给前端/排障）。

跑法：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_check_wecom_cli_missing_diagnosis.py

退出码非零 = 有断言失败。
"""
import asyncio
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'mcp-hub'))

from mcp_hub.wecom_cli import auth as cli_auth  # noqa: E402
from mcp_hub.wecom_cli import runner  # noqa: E402

fails = []
oks = 0


def chk(name, ok, detail=''):
    global oks
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''), flush=True)
    if ok:
        oks += 1
    else:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


def reset_cache():
    """bin_path 有进程级缓存，每个场景必须先清掉。"""
    runner._bin_cache = None


def main():
    old_env = os.environ.get('AIOS_WECOM_CLI_BIN')
    tmp = tempfile.mkdtemp(prefix='clidiag-')
    try:
        # ============ R1：env 指向不存在的路径 ============
        print('\n=== R1：env 指向不存在的路径 ===')
        missing = os.path.join(tmp, 'wecom-cli')          # 故意不创建
        os.environ['AIOS_WECOM_CLI_BIN'] = missing
        reset_cache()
        err = None
        try:
            runner.bin_path()
        except BaseException as exc:  # noqa: BLE001
            err = exc
        chk('R1 抛 CliError（不是裸 FileNotFoundError）',
            isinstance(err, runner.CliError), type(err).__name__)
        chk('R1 消息含「未找到企微 CLI」',
            err is not None and '未找到企微 CLI' in str(err), err)
        chk('R1 消息带出实际查找的路径',
            err is not None and missing in str(err), err)

        # ============ R2：probe 不抛 ============
        print('\n=== R2：probe() 不抛异常 ===')
        reset_cache()
        info = runner.probe()
        chk('R2 probe 不抛且 ok=False', info.get('ok') is False, info)
        chk('R2 probe 回显路径', info.get('path') == missing, info.get('path'))
        chk('R2 probe 带错误说明', bool(info.get('error')), info.get('error'))

        # ============ R3：status 不炸 ============
        print('\n=== R3：cli_auth.status() 应回 unauthorized 而不是抛 ===')
        reset_cache()
        # 造一个「看起来已授权」的目录：profiles.cli_dir 会补 personal/ 那层，
        # 把 credentials.enc 放到 prof/personal/ 下即可让 is_authorized=True，
        # 逼 status 真的去起子进程（那一步才会撞上「CLI 不存在」）。
        prof = Path(tmp) / 'profile'
        (prof / 'personal').mkdir(parents=True, exist_ok=True)
        (prof / 'personal' / 'credentials.enc').write_bytes(b'enc:dummy')
        chk('R3 前置：dummy 凭据被判为已授权（否则测不到子进程那一步）',
            cli_auth.profiles.is_authorized(prof) is True)
        os.environ['AIOS_WECOM_CLI_BIN'] = missing
        reset_cache()
        st3, err3 = None, None
        try:
            st3 = asyncio.run(cli_auth.status(prof))
        except BaseException as exc:  # noqa: BLE001
            err3 = exc
        chk('R3 status 不抛异常（REST 不会 500）', err3 is None, repr(err3))
        chk('R3 status 回 unauthorized（与「未扫码」同档，但诊断在 cli 字段里）',
            st3 == 'unauthorized', st3)

        # ============ R4：正向对照 ============
        print('\n=== R4：正向对照（env 指向真实可执行文件）===')
        real = os.path.join(tmp, 'real-cli')
        with open(real, 'w') as f:
            f.write('#!/bin/sh\necho ok\n')
        os.chmod(real, os.stat(real).st_mode | stat.S_IXUSR)
        os.environ['AIOS_WECOM_CLI_BIN'] = real
        reset_cache()
        err4 = None
        try:
            got = runner.bin_path()
        except BaseException as exc:  # noqa: BLE001
            got, err4 = None, exc
        chk('R4 返回该路径', got == real, (got, err4))
        reset_cache()
        chk('R4 probe.ok=True', runner.probe().get('ok') is True, runner.probe())

        # ============ R5：路径存在但不是可执行文件 ============
        print('\n=== R5：路径存在但不可执行 ===')
        # R5a 跨平台可造：同名的是个**目录**（os.path.isfile 为假）
        as_dir = os.path.join(tmp, 'cli-is-a-dir')
        os.makedirs(as_dir, exist_ok=True)
        os.environ['AIOS_WECOM_CLI_BIN'] = as_dir
        reset_cache()
        err5 = None
        try:
            runner.bin_path()
        except BaseException as exc:  # noqa: BLE001
            err5 = exc
        chk('R5a 同名是目录 ⇒ 抛 CliError', isinstance(err5, runner.CliError),
            type(err5).__name__)

        if sys.platform != 'win32':
            # Windows 上 os.access(..., os.X_OK) 对任何存在的文件都返回 True，
            # 造不出「有文件但不可执行」；这条只在 Linux（= 生产）上有意义。
            noexec = os.path.join(tmp, 'no-exec-cli')
            with open(noexec, 'w') as f:
                f.write('not a program\n')
            os.chmod(noexec, stat.S_IRUSR | stat.S_IWUSR)
            os.environ['AIOS_WECOM_CLI_BIN'] = noexec
            reset_cache()
            err5b = None
            try:
                runner.bin_path()
            except BaseException as exc:  # noqa: BLE001
                err5b = exc
            chk('R5b 有文件但无 x 位 ⇒ 抛 CliError（只读文件不许蒙混）',
                isinstance(err5b, runner.CliError), type(err5b).__name__)
            chk('R5b 消息含「不可执行」', err5b is not None and '不可执行' in str(err5b), err5b)
        else:
            chk('R5b 跳过：Windows 无 x 位语义（Linux 生产上生效）', True, 'platform=win32')
    finally:
        if old_env is None:
            os.environ.pop('AIOS_WECOM_CLI_BIN', None)
        else:
            os.environ['AIOS_WECOM_CLI_BIN'] = old_env
        reset_cache()

    # ============ S1：REST 面透出 cli 诊断 ============
    print('\n=== S1：静态契约 ===')
    api = os.path.join(REPO, 'mcp-hub', 'mcp_hub', 'wecom_cli', 'admin_api.py')
    with open(api, encoding='utf-8') as f:
        src = f.read()
    chk('S1 _status 透出 cli 诊断', '"cli": cli' in src, 'count=%d' % src.count('"cli": cli'))
    chk('S1 两个返回分支都带（NotBound 早退 + 正常）', src.count('"cli": cli') == 2,
        'count=%d' % src.count('"cli": cli'))
    chk('S1 _status 里调用了 runner.probe()', 'runner.probe()' in src)

    print('\n' + ('=' * 60))
    if fails:
        print('FAILED %d / %d' % (len(fails), oks + len(fails)))
        for x in fails:
            print('  - ' + x)
        return 1
    print('ALL PASS  %d 项' % oks)
    return 0


if __name__ == '__main__':
    sys.exit(main())
