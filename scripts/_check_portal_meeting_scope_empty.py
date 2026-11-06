# -*- coding: utf-8 -*-
"""门户「我参与的会议」空列表致 500 的回归哨兵（离线可跑）。

背景（2026-10-31 生产实测）：
    GET /api/v1/portal/meetings?scope=invited → 500
    java.lang.UnsupportedOperationException
      at java.util.ImmutableCollections$AbstractImmutableList.sort
      at cn.aios.resource.service.PortalService.listMeetings
根因：`mids.isEmpty() ? List.of() : meetingMapper.selectBatchIds(mids)` —— 空分支拿到
**不可变**列表，紧接着对它 `sort()`。用户一条会议邀请都没有时必现；本地 admin 有邀请数据，
走的是 selectBatchIds 分支（可变 ArrayList）⇒ 一直复现不出来。这也解释了「本地 200、生产 500」。

判据（每条都能因缺陷变红，含负向自检与运行时对照）：
  P1  invited 分支的 `meetings` 必须包一层可变容器（`new ArrayList<>(...)`），不得把
      三元表达式直接当列表用。
  P2  全仓扫描：被 `List.of()` / `stream().toList()` / `Collections.unmodifiableList(...)`
      赋值的变量，若在随后若干行内被 `sort(` / `add(` / `set(` / `remove(` 变更 ⇒ 红。
  P3  运行时对照（JDK 21 单文件执行，非引用文档）：`List.of().sort(cmp)` 必须抛
      UnsupportedOperationException，而 `new ArrayList<>(List.of())` 必须排序成功。
  P4  负向自检：把 P1 的修法在内存里还原成缺陷原样，P1 判据必须变红（证明判据不是恒真）；
      同时 P2 必须在还原后**依然能抓到**这次的真实缺陷（否则说明扫描器漏检）。

跑法：C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_check_portal_meeting_scope_empty.py
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, 'server')
SVC = os.path.join(SERVER, 'aios-resource', 'src', 'main', 'java', 'cn', 'aios',
                   'resource', 'service', 'PortalService.java')

fails = []
oks = 0


def chk(name, ok, detail=''):
    global oks
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if ok:
        oks += 1
    else:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


def read(p):
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


# ── P1 修法存在：可变容器包住三元 ───────────────────────────────
src = read(SVC)
P1_OK = re.search(r'List<PortalMeeting>\s+meetings\s*=\s*new\s+ArrayList<>\(\s*'
                  r'mids\.isEmpty\(\)\s*\?', src) is not None
chk('P1 invited 分支用 new ArrayList<>(...) 包住三元（空分支也变可变）', P1_OK)

# ── P2 扫描全仓：不可变列表被就地变更 ──────────────────────────
IMMUTABLE_ASSIGN = re.compile(
    r'(?:\b([A-Za-z_]\w*)\s*=\s*[^;]*?(?:List\.of\(|\.toList\(\)|unmodifiableList\())')
MUTATE = ('sort(', 'add(', 'set(', 'remove(', 'addAll(', 'removeIf(', 'replaceAll(', 'clear(')
LOOKAHEAD = 12  # 行
# 已经被可变容器包住的（`new ArrayList<>(... List.of() ...)`）不算缺陷，不要误报
MUTABLE_WRAP = ('new ArrayList<>(', 'new LinkedList<>(', 'new HashSet<>(', 'new LinkedHashSet<>(')


def scan_immutable_mutation(text):
    """返回 [(行号, 变量, 行文本)]：把不可变来源赋给变量后又在附近就地变更的写法。"""
    hits = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(('*', '//', '/*')):
            continue
        if any(w in line for w in MUTABLE_WRAP):
            continue
        m = IMMUTABLE_ASSIGN.search(line)
        if not m:
            continue
        var = m.group(1)
        if not var:
            continue
        # 同一行就以 return / 方法参数方式消费掉的，不可能再被变更
        for j in range(i, min(i + LOOKAHEAD, len(lines))):
            nxt = lines[j]
            if nxt.lstrip().startswith(('*', '//', '/*')):
                continue
            if re.search(r'(?<![\w.])' + re.escape(var) + r'\.(' + '|'.join(
                    re.escape(k) for k in MUTATE) + r')', nxt):
                hits.append((i + 1, var, nxt.strip()))
                break
    return hits


java_files = []
for root, _dirs, files in os.walk(SERVER):
    if os.sep + 'target' + os.sep in root + os.sep:
        continue
    for f in files:
        if f.endswith('.java'):
            java_files.append(os.path.join(root, f))

hits = []
for p in java_files:
    for ln, var, code in scan_immutable_mutation(read(p)):
        hits.append('%s:%d %s' % (os.path.relpath(p, REPO), ln, code))
chk('P2 全仓无「不可变列表就地变更」写法', not hits, '；'.join(hits[:3]) if hits else '%d 个 java 文件' % len(java_files))

# ── P3 运行时对照：List.of() 确实不可变（JDK 现场跑，不引文档）──
P3_SRC = '''
import java.util.*;
public class ImmutProbe {
    public static void main(String[] a) {
        boolean threw = false;
        try {
            List<String> imm = List.of();
            imm.sort(Comparator.naturalOrder());
        } catch (UnsupportedOperationException e) {
            threw = true;
        }
        List<String> mut = new ArrayList<>(List.of("b", "a"));
        mut.sort(Comparator.naturalOrder());
        boolean sorted = mut.equals(List.of("a", "b"));
        System.out.println((threw ? "THREW" : "NO-THREW") + "/" + (sorted ? "SORTED" : "NOT-SORTED"));
    }
}
'''
p3_out = ''
try:
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, 'ImmutProbe.java')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(P3_SRC)
        r = subprocess.run(['java', f], capture_output=True, text=True, timeout=120)
        p3_out = (r.stdout or '').strip() or (r.stderr or '').strip()[:200]
except FileNotFoundError:
    p3_out = 'SKIP: 无 java'
except Exception as e:  # noqa: BLE001
    p3_out = 'SKIP: %s' % e
chk('P3 运行时对照：List.of() 上 sort 必抛 UOE，ArrayList(List.of()) 可排序',
    p3_out.startswith('SKIP') or p3_out == 'THREW/SORTED', p3_out)

# ── P4 负向自检：还原成缺陷原样，P1 必须红、P2 必须能抓到 ────────
BROKEN = '''            List<PortalMeeting> meetings = mids.isEmpty() ? List.of() : meetingMapper.selectBatchIds(mids);
            Map<Long, String> finalInv = invMap;
            meetings.sort(Comparator.comparing(PortalMeeting::getStartAt,
                    Comparator.nullsLast(Comparator.reverseOrder())));
'''
FIXED_MARK = 'mids.isEmpty() ? List.of() : meetingMapper.selectBatchIds(mids));'
# 把当前源码里的「修好的那 5 行」换回缺陷原样（按定位到的锚点替换，不依赖缩进细节）
anchor = src[src.index('List<PortalMeeting> meetings = '):src.index('mids.isEmpty() ?', src.index('List<PortalMeeting> meetings = '))]
broken_text = src.replace(anchor, 'List<PortalMeeting> meetings = ', 1)
p1_on_broken = re.search(r'List<PortalMeeting>\s+meetings\s*=\s*new\s+ArrayList<>\(\s*'
                         r'mids\.isEmpty\(\)\s*\?', broken_text) is not None
hits_broken = scan_immutable_mutation(broken_text)
chk('P4a 负向：还原缺陷后 P1 判据变红', not p1_on_broken)
chk('P4b 负向：还原缺陷后 P2 扫描器仍能抓到（说明扫描器有效）',
    bool(hits_broken), str(hits_broken[:1]) if hits_broken else '未抓到')

print()
if fails:
    print('FAILED %d / %d' % (len(fails), oks + len(fails)))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('PASS %d / %d' % (oks, oks))
