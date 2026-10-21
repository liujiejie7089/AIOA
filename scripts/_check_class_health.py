# -*- coding: utf-8 -*-
"""编译产物健康检查：拦掉两类「构建说成功、运行时才炸」的坏 class。

为什么需要它（本仓已各踩过一次，代价都是「后端起不来 / 接口莫名 500」）
----------------------------------------------------------------------
1) **ECJ 错误类**：VS Code 的 Java 扩展（redhat.java）用 Eclipse JDT 编译并直接写
   本仓的 `target/classes`。JDT 编译**失败时不会中止**，而是生成一个 class，
   其方法体只有 `throw new Error("Unresolved compilation problems: ...")`。
   Maven 之后若判定 "Nothing to compile" 就会把这个坏类原样打进 jar ——
   javac 完全无辜，日志里也全是 BUILD SUCCESS，只有启动时才炸。
2) **零长度 Code**：方法有 Code 属性但 code_length=0（正常构造器至少 5 字节）。
   JVM 报 `ClassFormatError: Invalid method Code length 0`，且 `javap` 看起来「一切正常」。

用法：python scripts/_check_class_health.py [--root server] [--fix]
  --fix  发现坏类时提示对应的 clean 重编命令（默认只报告，退出码=坏类数）
退出码 = 坏类个数（0 = 健康）。
"""
from __future__ import annotations

import argparse
import glob
import os
import struct
import sys

ECJ_MARK = b"Unresolved compilation"


def zero_code_methods(path: str) -> list[str]:
    """返回 code_length=0 的方法签名（空列表 = 正常）。只做最小 class 解析，不依赖第三方库。"""
    try:
        b = open(path, "rb").read()
    except OSError:
        return []
    if len(b) < 10 or b[:4] != b"\xca\xfe\xba\xbe":
        return []
    pos = [8]

    def u1():
        v = b[pos[0]]; pos[0] += 1; return v

    def u2():
        v = struct.unpack(">H", b[pos[0]:pos[0] + 2])[0]; pos[0] += 2; return v

    def u4():
        v = struct.unpack(">I", b[pos[0]:pos[0] + 4])[0]; pos[0] += 4; return v

    try:
        cp_n = u2()
        cp: dict[int, str] = {}
        k = 1
        while k < cp_n:
            t = u1()
            if t == 1:
                ln = u2(); cp[k] = b[pos[0]:pos[0] + ln].decode("utf-8", "replace"); pos[0] += ln
            elif t in (7, 8, 16, 19, 20):
                u2()
            elif t == 15:
                u1(); u2()
            elif t in (3, 4, 9, 10, 11, 12, 17, 18):
                u4()
            elif t in (5, 6):
                u4(); u4(); k += 1
            k += 1

        u2(); u2(); u2()
        for _ in range(u2()):
            u2()

        def skip_attrs():
            n = u2()
            for _ in range(n):
                u2(); ln = u4(); pos[0] += ln

        for _ in range(u2()):
            u2(); u2(); u2(); skip_attrs()

        bad = []
        for _ in range(u2()):
            acc = u2(); name = cp.get(u2(), "?"); desc = cp.get(u2(), "?"); n = u2()
            for _ in range(n):
                an = cp.get(u2(), "?"); ln = u4(); start = pos[0]
                if an == "Code":
                    u2(); u2()
                    cl = u4()
                    # 抽象(0x0400)/native(0x0100) 本来就没有 Code，走不到这里
                    if cl == 0:
                        bad.append("%s%s (acc=0x%04x)" % (name, desc, acc))
                pos[0] = start + ln
        return bad
    except Exception:
        return []   # 解析不了就不判（保持静默，不制造假阳性）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="server")
    ap.add_argument("--fix", action="store_true")
    args = ap.parse_args()

    files = glob.glob(os.path.join(args.root, "*", "target", "classes", "**", "*.class"), recursive=True)
    ecj, zero = [], []
    for f in files:
        try:
            if ECJ_MARK in open(f, "rb").read():
                ecj.append(f)
                continue
        except OSError:
            continue
        z = zero_code_methods(f)
        if z:
            zero.append((f, z))

    print("扫描 class 文件：%d 个（%s/*/target/classes）" % (len(files), args.root))
    for f in ecj:
        print("  [ECJ 错误类] %s" % f)
    for f, z in zero:
        print("  [零长度 Code] %s -> %s" % (f, "; ".join(z)))

    total = len(ecj) + len(zero)
    if total == 0:
        print("健康：无 ECJ 错误类、无零长度 Code ✅")
        return 0

    print("\n发现 %d 个坏 class。清法（按模块）：" % total)
    mods = sorted({os.path.normpath(f).split(os.sep)[1] for f in ecj + [x[0] for x in zero]})
    for m in mods:
        print("  cd server && mvn -o -pl %s clean compile" % m)
    print("然后整仓重打包：cd server && mvn -o -DskipTests package（务必先停掉后端，jar 被占用会失败）")
    if args.fix:
        print("\n（--fix 只提示命令，不自动执行：clean 会删 target，需你确认时机）")
    return total


if __name__ == "__main__":
    sys.exit(min(main(), 120))
