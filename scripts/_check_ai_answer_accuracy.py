# -*- coding: utf-8 -*-
"""AI 回答准确性 + 生产/本地配置分离的回归哨兵（2026-10-31 用户对话现场）。

A 组 · 意图误判（运行时判据，直接调 detect_action，不是看源码）
  用户现场：「把这个文件传到我的企业微信上去」被判成 UPLOAD_FILE ⇒
  H5 回「这个操作要归属到某个项目：请先在「任务 → 项目」里进入一个项目」——答非所问。
  同理「请解析我上传的文档」是阅读诉求，也不该弹项目上传窗口。

B 组 · 提示词纪律（静态判据，钉住四段真实错答的修法）
  ① 企业微信被答成邮箱；② 要 5 封明细被回「内容较长无法显示」；
  ③ 已附文件仍被反问「哪个文件」；④ 解析文档时把 token 原样复述。

C 组 · 生产/本地配置分离（静态判据）
  两套模板的 WECOM_MOCK / WECOM_CONNECTOR_KEY / CLI 目录必须不同，
  且 compose 必须透传 Java 侧连接器加密钥（此前空转，等于生产用 dev 占位 ⇒ 凭据明文）。

跑法：D:/aios/agent/.venv/Scripts/python.exe scripts/_check_ai_answer_accuracy.py
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'agent'))

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


def read(rel):
    with open(os.path.join(REPO, rel), 'r', encoding='utf-8') as f:
        return f.read()


# ── A 组：意图识别（运行时）──────────────────────────────────
from aios_ai.intent import intake  # noqa: E402

NOT_UPLOAD = [
    ('把文件上传到企业微信', '外部投递（企业微信）'),
    ('把这个文件传到我的企业微信上去', '外部投递（用户原话）'),
    ('把文件发给同事张三', '外部投递（同事）'),
    ('请解析我上传的文档', '阅读诉求（用户原话）'),
]
for text, why in NOT_UPLOAD:
    chk('A 不应判项目上传：%s（%s）' % (text, why), intake.detect_action(text) is None,
        str(intake.detect_action(text)))

STILL_UPLOAD = [
    ('上传文件', '裸上传仍是项目上传'),
    ('把项目合同传上去', '项目材料上传'),
    ('把文件上传到项目里', '含「项目」时外部目标词不豁免'),
]
for text, why in STILL_UPLOAD:
    chk('A 仍应判项目上传：%s（%s）' % (text, why), intake.detect_action(text) == 'UPLOAD_FILE',
        str(intake.detect_action(text)))

# A8 负向自检：把外部目标词表换成永不命中，第一句必须**变回** UPLOAD_FILE。
# 若不变，说明该句本来就没命中，上面的「通过」是假绿。
orig = intake._UPLOAD_EXTERNAL_TARGET
try:
    intake._UPLOAD_EXTERNAL_TARGET = re.compile(r'(?!x)x')
    reverted = intake.detect_action('把文件上传到企业微信')
finally:
    intake._UPLOAD_EXTERNAL_TARGET = orig
chk('A8 负向：去掉外部目标排除后必须变回 UPLOAD_FILE（证明排除真在起作用）',
    reverted == 'UPLOAD_FILE', str(reverted))

# ── B 组：提示词纪律（静态）──────────────────────────────────
builder = read('agent/aios_ai/prompt/builder.py')
chk('B1 有【连接器语义路由】段且点名企微消息工具',
    '【连接器语义路由】' in builder and 'recent_group_sessions' in builder
    and 'session_messages' in builder)
chk('B2 不得把邮箱当成企业微信消息',
    '不得**把邮箱文件夹' in builder or '当成「企业微信的消息」' in builder)
chk('B3 要明细必须逐个调用读取工具，不得拿「内容较长」拒答',
    '逐个调用读取工具' in builder and '内容较长' in builder and 'read_message' in builder)
chk('B4 企微只读边界写死（不发消息/不传文件）',
    '不支持发消息、传文件' in builder)
chk('B5 有【附件与凭据】段：不得反问哪个文件',
    '【附件与凭据】' in builder and '请明确哪个文件' in builder)
chk('B6 凭据不得原样复述，且要掩码 + 提醒吊销',
    '不得原样复述' in builder and '掩码' in builder and '吊销' in builder)

# ── C 组：生产/本地配置分离（静态）────────────────────────────
dev = read('deploy/.env.development')
prod = read('deploy/.env.production')


def val(src, key):
    m = re.search(r'^' + re.escape(key) + r'=(.*)$', src, re.M)
    return m.group(1).strip() if m else None


chk('C1 两套 WECOM_MOCK 不同（本地 1 / 生产 0）',
    val(dev, 'WECOM_MOCK') == '1' and val(prod, 'WECOM_MOCK') == '0',
    'dev=%s prod=%s' % (val(dev, 'WECOM_MOCK'), val(prod, 'WECOM_MOCK')))
chk('C2 两套 WECOM_CONNECTOR_KEY 不同（生产不得复用本地开发密钥）',
    val(dev, 'WECOM_CONNECTOR_KEY') != val(prod, 'WECOM_CONNECTOR_KEY'))
chk('C3 CLI 目录不互抄（本地仓库相对 / 生产 /data/aioa）',
    (val(dev, 'AIOS_WECOM_CLI_ROOT_DIR') or '').startswith('../data')
    and (val(prod, 'AIOS_WECOM_CLI_ROOT_DIR') or '').startswith('/data/aioa'),
    'dev=%s prod=%s' % (val(dev, 'AIOS_WECOM_CLI_ROOT_DIR'), val(prod, 'AIOS_WECOM_CLI_ROOT_DIR')))
chk('C4 生产必须显式要求 Java 侧连接器加密钥（不能再用 dev 占位默认值）',
    'AIOS_CONNECTOR_SECRET_KEY' in prod and val(prod, 'AIOS_CONNECTOR_SECRET_KEY') == '')
chk('C5 compose 透传 AIOS_CONNECTOR_SECRET_KEY（否则 .env 里改它空转）',
    'AIOS_CONNECTOR_SECRET_KEY: ${AIOS_CONNECTOR_SECRET_KEY:-'
    in read('deploy/docker-compose.yml'))

print()
if fails:
    print('FAILED %d / %d' % (len(fails), oks + len(fails)))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('PASS %d / %d' % (oks, oks))
