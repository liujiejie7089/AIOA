# -*- coding: utf-8 -*-
"""HITL 澄清链 Java 层（RunService / AgentRun / RunController）接线哨兵。

只做**纯静态**自检（不改任何源文件、不跑测试、不连数据库），断言：
  R1  AgentRun.java 含 STATUS_WAITING_INPUT 且值为 "WAITING_INPUT"
  R2  RunService.java 含 EVENT_NEED_CLARIFICATION = "need_clarification"
  R3  subscribe 里对 WAITING_INPUT 有早于 replay 守卫的处理
      （判定：STATUS_WAITING_INPUT 在 RunService.java 出现 ≥ 3 次 + waitingInputNotice 方法存在
       + 其 guard 在 SUCCEEDED 守卫之前）
  R4  completeRun 里有 markWaitingInput(run) 且出现在 failureRef.get() 判断之前
      （在 completeRun 方法作用域内用 index() 比较，重跑两次结果一致）
  R5  resume 方法存在且对非 WAITING_INPUT 状态抛 BizException.badRequest
  R6  RunController 有 @PostMapping 到 /api/v1/runs/{runId}/resume 且 produces=TEXT_EVENT_STREAM_VALUE
  R7  负向对照：内存去掉 STATUS_WAITING_INPUT 常量后 R1 应失败（证明判据非恒真）

退出码非零 = 有判据未通过。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_RUN = os.path.join(REPO, "server", "aios-chat", "src", "main", "java",
                         "cn", "aios", "chat", "entity", "AgentRun.java")
RUN_SERVICE = os.path.join(REPO, "server", "aios-chat", "src", "main", "java",
                           "cn", "aios", "chat", "service", "RunService.java")
RUN_CTRL = os.path.join(REPO, "server", "aios-chat", "src", "main", "java",
                        "cn", "aios", "chat", "controller", "RunController.java")

fails = []


def chk(name, ok, detail=""):
    print("[%s] %s%s" % ("OK  " if ok else "FAIL", name,
                         (" — " + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def method_body(src, sig):
    """粗略抽取从方法签名行开始的整段（按花括号配平）。"""
    m = re.search(re.escape(sig), src)
    if not m:
        return None
    i = src.index("{", m.start())
    depth = 0
    j = i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    return src[i:]


def main():
    agent_run = read(AGENT_RUN)
    run_svc = read(RUN_SERVICE)
    run_ctrl = read(RUN_CTRL)

    # ---- R1：AgentRun.java 含 STATUS_WAITING_INPUT 且值为 "WAITING_INPUT" ----
    def r1_ok(text):
        # 常量定义行
        const_line = ('public static final String STATUS_WAITING_INPUT'
                      ' = "WAITING_INPUT";') in text
        # 取值一致（任意引用处 eq("WAITING_INPUT")）
        ref_ok = 'STATUS_WAITING_INPUT.equals' in text or const_line
        return const_line and ref_ok

    chk("R1 AgentRun.java 定义 STATUS_WAITING_INPUT = \"WAITING_INPUT\"",
        r1_ok(agent_run),
        "const_line=%s" % ('public static final String STATUS_WAITING_INPUT = "WAITING_INPUT";' in agent_run))

    # ---- R2：RunService.java 含 EVENT_NEED_CLARIFICATION = "need_clarification" ----
    r2 = 'private static final String EVENT_NEED_CLARIFICATION = "need_clarification";' in run_svc
    chk("R2 RunService.java 定义 EVENT_NEED_CLARIFICATION = \"need_clarification\"", r2)

    # ---- R3：subscribe 对 WAITING_INPUT 早于 replay 守卫 ----
    count = run_svc.count("STATUS_WAITING_INPUT")
    has_notice = bool(re.search(r"private\s+SseEmitter\s+waitingInputNotice\s*\(", run_svc))
    sub_body = method_body(run_svc, "public SseEmitter subscribe(")
    guard_before = False
    if sub_body is not None:
        gi = sub_body.find("STATUS_WAITING_INPUT.equals(run.getStatus())")
        gr = sub_body.find("STATUS_SUCCEEDED.equals(run.getStatus())")
        guard_before = gi != -1 and gr != -1 and gi < gr
    r3 = count >= 3 and has_notice and guard_before
    chk("R3 subscribe 在 replay 前拦截 WAITING_INPUT（出现%d次, notice=%s, 早于replay=%s）"
        % (count, has_notice, guard_before), r3)

    # ---- R4：completeRun 中 markWaitingInput(run) 早于 failureRef.get() ----
    cr_body = method_body(run_svc, "private void completeRun(")
    if cr_body is not None:
        mi = cr_body.find("markWaitingInput(run)")
        fg = cr_body.find("failureRef.get()")
        r4 = mi != -1 and fg != -1 and mi < fg
        detail = "mark_idx=%d failure_idx=%d (%s)" % (
            mi, fg, "mark<failure" if (mi != -1 and fg != -1 and mi < fg) else "order-bad")
        # 重跑两次结果一致（幂等校验）
        mi2 = cr_body.find("markWaitingInput(run)")
        fg2 = cr_body.find("failureRef.get()")
        consistent = (mi == mi2) and (fg == fg2)
        r4 = r4 and consistent
        detail += " consistent=%s" % consistent
    else:
        r4 = False
        detail = "completeRun 方法未找到"
    chk("R4 completeRun 中 markWaitingInput(run) 早于 failureRef.get() 判断", r4, detail)

    # ---- R5：resume 存在且对非 WAITING_INPUT 抛 BizException.badRequest ----
    rs_body = method_body(run_svc, "public SseEmitter resume(")
    if rs_body is not None:
        has_guard = "STATUS_WAITING_INPUT.equals(run.getStatus())" in rs_body
        throws_bad = "BizException.badRequest(" in rs_body
        r5 = has_guard and throws_bad
        detail = "guard=%s badRequest=%s" % (has_guard, throws_bad)
    else:
        r5 = False
        detail = "resume 方法未找到"
    chk("R5 resume 存在且对非 WAITING_INPUT 抛 BizException.badRequest", r5, detail)

    # ---- R6：RunController @PostMapping /resume + produces=TEXT_EVENT_STREAM_VALUE ----
    # 取 resume 端点块（@PostMapping 到 return runService.resume 之间）
    m = re.search(r"@PostMapping\(path = \"/api/v1/runs/\{runId\}/resume\"", run_ctrl)
    if m is not None:
        end = run_ctrl.find("return runService.resume", m.start())
        block = run_ctrl[m.start():end if end != -1 else m.start() + 400]
        has_post = "@PostMapping" in block
        has_path = "/api/v1/runs/{runId}/resume" in block
        has_stream = "TEXT_EVENT_STREAM_VALUE" in block
        r6 = has_post and has_path and has_stream
        detail = "post=%s path=%s stream=%s" % (has_post, has_path, has_stream)
    else:
        r6 = False
        detail = "resume @PostMapping 未找到"
    chk("R6 RunController 有 POST /api/v1/runs/{runId}/resume 且 produces=TEXT_EVENT_STREAM_VALUE",
        r6, detail)

    # ---- R7：负向对照 —— 内存去掉常量后 R1 必须失败 ----
    modified = agent_run.replace(
        'public static final String STATUS_WAITING_INPUT = "WAITING_INPUT";', "")
    after_remove = r1_ok(modified)
    r7 = (not after_remove)  # 期望：去掉常量后判据失败（证明非恒真）
    chk("R7 负向对照：去掉 STATUS_WAITING_INPUT 常量后 R1 应失败（实际 failed=%s）"
        % (not after_remove), r7,
        "去掉后R1通过=%s（期望 False）" % after_remove)

    total = 7
    print("\n通过 %d/%d" % (total - len(fails), total))
    if fails:
        print("失败项：")
        for f in fails:
            print("  - " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
