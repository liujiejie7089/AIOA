# -*- coding: utf-8 -*-
"""可执行产物哨兵：`aios-boot` 的 jar 必须是**胖 jar**（含 BOOT-INF/lib）。

为什么必须有这一条 —— 2026-10-11 实际踩到的缺陷，现象与成因：
  为了隔离验证，构建时用过 `-Dspring-boot.repackage.skip=true`，
  于是 `server/aios-boot/target/aios-boot-0.1.0-SNAPSHOT.jar` 被换成了一个
  **170KB 的「瘦 jar」**（只有本工程的 classes，没有 BOOT-INF/lib）。
  更糟的是：当时已有一个**更早启动**的后端进程在跑。JVM 是**按需加载** class 的 ——
  启动时已加载的类照常工作，**尚未加载**的类则再也读不到。于是：

    POST /api/v1/conversations/{id}/runs  →  500
    java.lang.NoClassDefFoundError: cn/aios/chat/dto/RunCreatedResponse
    GET  /api/v1/admin/org-configs        →  500
    java.lang.NoClassDefFoundError: org/springframework/web/servlet/mvc/LastModified

  两个症状都**与业务代码无关**，日志里是 ClassNotFound，源码里那个类明明存在，
  `mvn test` 也全绿（测试跑的是 target/classes，不读 jar）——
  唯一能静态发现它的地方，就是**检查产物本身**。这就是本哨兵存在的理由。

判据（全部只读产物与源码，不启动服务）：
  J1  目标 jar 存在（缺失 ⇒ SKIP 且非 0，不伪装 PASS）
  J2  ★含 `BOOT-INF/lib/` 且内嵌 jar 数 ≥ 50（胖 jar 的判据）
  J3  MANIFEST 的 Main-Class 指向 Spring Boot loader、
      Start-Class = cn.aios.boot.AiosBootApplication（否则 jar 不可执行）
  J4  `BOOT-INF/classes/cn/aios/boot/AiosBootApplication.class` 在包内（本工程代码确实进了包）
  J5  关键模块 jar 内嵌**且各自非空**：aios-chat / aios-project / aios-resource / aios-security
  J6  ★定点回归：本次故障类 `cn/aios/chat/dto/RunCreatedResponse`
      必须能在**内嵌的 aios-chat jar 内部**解析出来（J2/J5 的「到位写法」）

负向对照（证明判据有区分力，不是恒真）：
  N1  合成的「只有 MANIFEST、无 BOOT-INF/lib」的瘦 jar ⇒ 必须判**不是胖 jar**
  N2  若同目录存在 `.jar.original`（repackage 前的瘦 jar）⇒ 对它必须判**不是胖 jar**

用法：
    python scripts/_check_boot_jar_fat.py                  # 检查默认产物
    python scripts/_check_boot_jar_fat.py --jar <path>     # 检查指定 jar
"""
import argparse
import io
import json
import os
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOT_TARGET = os.path.join(REPO, 'server', 'aios-boot', 'target')
DEFAULT_JAR = os.path.join(BOOT_TARGET, 'aios-boot-0.1.0-SNAPSHOT.jar')

# 内嵌模块 jar -> 该 jar 内必须能解析出的一个类（证明它不是一个空壳）
REQUIRED_MODULE_CLASSES = [
    ('aios-chat', 'cn/aios/chat/dto/RunCreatedResponse.class'),          # ★ 本次故障类
    ('aios-project', 'cn/aios/project/controller/PmDigitalWorkerController.class'),
    ('aios-resource', 'cn/aios/resource/support/SysConfigGroups.class'),
    ('aios-security', 'cn/aios/security/PermissionCatalog.class'),
]
MIN_LIBS = 50

PASS = []
FAIL = []


def chk(cid, cond, detail=''):
    (PASS if cond else FAIL).append(cid)
    print(('  [PASS] ' if cond else '  [FAIL] ') + cid + ('' if cond else '  <- ' + str(detail)[:300]))


def locate_jar(explicit=None):
    """返回被检查的 jar 路径；找不到返回 None。"""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    if os.path.isfile(DEFAULT_JAR):
        return DEFAULT_JAR
    if os.path.isdir(BOOT_TARGET):
        cands = sorted(
            os.path.join(BOOT_TARGET, n) for n in os.listdir(BOOT_TARGET)
            if n.endswith('.jar') and 'sources' not in n and 'javadoc' not in n
        )
        if cands:
            return cands[-1]
    return None


def inspect(jar_path):
    """只读地量出 jar 的关键事实；任何异常都以 available=False 返回（不抛）。"""
    out = {'available': True, 'libs': 0, 'manifest': '', 'classes': False,
           'embedded': {}, 'error': None}
    try:
        with zipfile.ZipFile(jar_path) as z:
            names = z.namelist()
            out['libs'] = len([n for n in names if n.startswith('BOOT-INF/lib/') and n.endswith('.jar')])
            out['classes'] = 'BOOT-INF/classes/cn/aios/boot/AiosBootApplication.class' in names
            try:
                out['manifest'] = z.read('META-INF/MANIFEST.MF').decode('utf-8', 'ignore')
            except KeyError:
                out['manifest'] = ''
            # 递归打开内嵌模块 jar：确认「内嵌」不等于「空壳」
            for mod, cls in REQUIRED_MODULE_CLASSES:
                entry = 'BOOT-INF/lib/%s-0.1.0-SNAPSHOT.jar' % mod
                got = None
                if entry in names:
                    try:
                        inner = zipfile.ZipFile(io.BytesIO(z.read(entry)))
                        inner_names = inner.namelist()
                        got = (cls in inner_names, len(inner_names))
                    except Exception as e:                       # 损坏的内嵌 jar
                        got = (False, 'open-failed: %s' % e)
                out['embedded'][mod] = got
    except Exception as e:
        out['available'] = False
        out['error'] = str(e)
    return out


def is_fat(info):
    """胖 jar 的三条硬判据（J2 + J3 + J4）。负向对照直接复用本函数。"""
    man = info.get('manifest') or ''
    loader_ok = ('Main-Class: org.springframework.boot.loader.launch.JarLauncher' in man
                 or 'Main-Class: org.springframework.boot.loader.JarLauncher' in man)
    start_ok = 'Start-Class: cn.aios.boot.AiosBootApplication' in man
    return (info.get('available') and info.get('libs', 0) >= MIN_LIBS
            and info.get('classes') and loader_ok and start_ok), {
        'libs': info.get('libs'), 'classes': info.get('classes'),
        'loader': loader_ok, 'startClass': start_ok}


def negative_controls(target_jar):
    """N1 合成瘦 jar；N2 真实的 .jar.original（若在）。"""
    ok = True
    tmp = os.path.join(tempfile.gettempdir(), '_fatjar_negative_control.jar')
    try:
        with zipfile.ZipFile(tmp, 'w') as z:
            z.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\r\n\r\n')
            z.writestr('cn/aios/boot/AiosBootApplication.class', b'\xca\xfe\xba\xbe')
        fat, det = is_fat(inspect(tmp))
        chk('N1 ★负向对照：合成瘦 jar（无 BOOT-INF/lib、无 Start-Class）必须被判「不是胖 jar」',
            not fat, det)
        ok = ok and (not fat)
    except Exception as e:
        chk('N1 合成瘦 jar 的负向对照可执行', False, e)
        ok = False
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass

    orig = target_jar + '.original'
    if os.path.isfile(orig):
        fat, det = is_fat(inspect(orig))
        chk('N2 ★负向对照：repackage 前的 .original（瘦 jar）必须被判「不是胖 jar」', not fat, det)
        ok = ok and (not fat)
    else:
        print('  [SKIP] N2 同目录无 .original，跳过该负向对照（不影响结论）')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jar', default=None, help='指定要检查的 jar（默认 server/aios-boot/target 下的产物）')
    args = ap.parse_args()

    print('[可执行产物哨兵 · aios-boot 必须是胖 jar]')
    jar = locate_jar(args.jar)
    if not jar:
        print('  [SKIP] 未找到 aios-boot 产物（%s）' % (args.jar or BOOT_TARGET))
        print('         前置不满足：先构建 —— cd server && bash mvnw -DskipTests -q package')
        print('\n合计：0 通过 / 1 失败（前置不满足，不伪装 PASS）')
        return 1

    info = inspect(jar)
    print('  目标：%s' % os.path.relpath(jar, REPO).replace('\\', '/'))

    chk('J1 产物可读（是合法 zip）', info['available'], info.get('error'))
    if not info['available']:
        print('\n合计：%d 通过 / %d 失败' % (len(PASS), len(FAIL)))
        return 1

    man = info['manifest']
    loader_ok = ('Main-Class: org.springframework.boot.loader.launch.JarLauncher' in man
                 or 'Main-Class: org.springframework.boot.loader.JarLauncher' in man)
    start_ok = 'Start-Class: cn.aios.boot.AiosBootApplication' in man

    chk('J2 ★含 BOOT-INF/lib 且内嵌 jar ≥ %d（瘦 jar 只有本工程 classes）' % MIN_LIBS,
        info['libs'] >= MIN_LIBS, '实际 %d 个内嵌 jar' % info['libs'])
    chk('J3 MANIFEST 可执行：Main-Class 指向 Spring Boot loader', loader_ok,
        man[:200].replace('\n', ' | '))
    chk('J3b MANIFEST 可执行：Start-Class = cn.aios.boot.AiosBootApplication', start_ok,
        man[:200].replace('\n', ' | '))
    chk('J4 本工程入口类已进包（BOOT-INF/classes/.../AiosBootApplication.class）',
        info['classes'])

    for mod, cls in REQUIRED_MODULE_CLASSES:
        got = info['embedded'].get(mod)
        if got is None:
            chk('J5 模块 %s 已内嵌' % mod, False, 'BOOT-INF/lib 中找不到 %s-*.jar' % mod)
            continue
        present, n = got
        chk('J5 模块 %s 已内嵌且非空（内含 %s）' % (mod, cls.split('/')[-1]), present,
            '内嵌条目数=%s' % n)

    # J6：把「到位」写成对故障本身的定点断言
    got = info['embedded'].get('aios-chat')
    chk('J6 ★定点回归：故障类 RunCreatedResponse 可在内嵌 aios-chat jar 内解析（否则 /runs 必 500）',
        bool(got and got[0]), 'aios-chat 内嵌状态=%s' % (got,))

    negative_controls(jar)

    print('\n合计：%d 通过 / %d 失败' % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
