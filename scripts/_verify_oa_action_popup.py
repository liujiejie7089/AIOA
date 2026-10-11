# -*- coding: utf-8 -*-
"""「识别到上传/上报意图 ⇒ 自动弹窗」的**浏览器级**验证（2026-10 需求，H5 侧）。

为什么单独有这一条，而不是只 grep 产物：
  · `scripts/_verify_project_isolation.py` 的 G 组只能证明产物里**有**这行代码；
  · Java 侧的 `WorkerIntakeActionPassthroughTest` 只能证明**契约**透传（action 出得来）；
  · 两者都证明不了「H5 拿到 `action` 之后真的把窗口弹给了用户」——那正是用户要的那一步。
  本脚本用真实 Chromium 载入**重建后的产物** `user-client/index.html`，
  直接驱动判定函数并断言 DOM 真的变了。

判据（每条都回到事实源头，不读界面自己的副本）：
  ① 不在项目内 → 不弹窗、只提示（否则会把「花费」记到不属于它的地方）；
  ② `REPORT_EXPENSE` → 真的出现花费表单（`.notif-mask` 内的 `#expAmt`），且正文里先有说明气泡；
  ③ `UPLOAD_FILE` → 先弹**可见上传窗口**（`.notif-mask.show` 新增恰好 1 层、内含 `#upFile`、标题「上传项目文档」），
     且弹窗那一刻**不自动唤起**文件选择器（见 G9b★）、**只在真实点击 `#upFile` 后才唤起**（见 G9c）；正文说明气泡照旧。
  ④ `action` 为 null/缺失 → **什么都不做**（负向对照：证明前三条的断言不是恒真）。

★ 负向对照（铁律 12 的同源要求）：④ 与「调用前先数一遍弹层数」共同保证
  ② 的 `== 1` 不是把已有 DOM 当成新弹的。

★ 关于 G9 的口径改动（为什么从「一调 `UPLOAD_FILE` 就断言发起文件选择」改成
  「弹窗不自动唤起 + 点击 `#upFile` 才唤起」）：
  旧实现 `oaUploadProjectDoc()` 是「动态造一个 `<input type=file>` 再立刻 `inp.click()`」，而它由
  `oaAfterOaAnswer()` 在 `await 整段回答流式生成` + `await /v1/workers/intent` **之后**才调用，此时距用户点
  「发送」已过数秒乃至数十秒，**浏览器要求的「用户手势瞬时激活」早已失效**，`click()` 被**静默忽略**
  （不报错、不弹窗）。所以旧口径在旧实现下其实也恒假——它抓不到任何东西。新实现改为先弹可见窗口，
  文件选择器只在用户**直接点击** `#upFile` 时才唤起，手势成立 ⇒ 选择器必然唤起。G9b 因而成为旧缺陷的
  定点判据：若有人把实现改回「延迟 `input.click()`」，弹窗那一刻会立刻触发选择器，G9b 即变红；G9c 再证明
  窗口里的 `#upFile` 入口是真能用的（不是空壳控件）。

前置：无需后端、无需登录态（页面用 `file://` 载入，绝大多数网络请求失败被产品代码自身吞掉）。
  唯独上传窗的「文件控件」要先等 `/docs/tree` 取到根文件夹才 `disabled=false`；无后端时该请求必败、
  控件会一直 disabled、G9c 点不动，故本脚本在打开上传窗之前用 `API.req` 桩把 `/docs/tree` 喂成
  「根文件夹已读到」（桩只劫持 tree 路径，其余请求仍走原实现），让产品自身的「取到文件夹才放开控件」
  逻辑正常走完；G9d 再回头核验 `#upFolder` 真的被填上、控件真的被解锁。
用法：python scripts/_verify_oa_action_popup.py
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "user-client" / "index.html"

PASS, FAIL = [], []


def chromium_exe():
    """返回本机已安装的 Chromium 可执行文件路径；找不到返回 None（交给 playwright 默认解析）。

    为什么要自己找：playwright 包版本与 `ms-playwright` 里已下载的浏览器**代号常常不一致**
    （例：包要 chromium_headless_shell-1243，而本机只装了 -1234）⇒ 直接 launch 会报
    「Executable doesn't exist」，那不是环境坏，只是没对上号。这里按代号降序挑一个真实存在的。
    """
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not root.exists():
        return None
    for pat in ("chromium-*/chrome-win64/chrome.exe",
                "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"):
        hits = sorted(root.glob(pat))
        if hits:
            return str(hits[-1])
    return None


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  <- " + str(detail)[:400]))


def dock_text(page):
    return page.eval_on_selector("#oaDockList", "el => el.innerText") or ""


def main():
    if not INDEX.exists():
        print("[FAIL] 产物不存在：%s" % INDEX)
        return 1
    html = INDEX.read_text(encoding="utf-8")
    chk("G0 产物已重建（含本轮新增的 oaMaybeProjectAction 与自检暴露）",
        "window.oaMaybeProjectAction" in html and "oaMaybeProjectAction" in html, INDEX)

    with sync_playwright() as pw:
        exe = chromium_exe()
        browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        page = browser.new_page(viewport={"width": 420, "height": 900})
        page.goto(INDEX.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(600)

        # 进入 OA 形态（与自检脚本既有做法一致：置 auth + mode 后调 oaBoot）
        page.evaluate("() => { document.body.classList.add('auth'); window.oaState.mode = 'oa'; window.oaBoot(); }")
        page.wait_for_timeout(400)
        chk("G1 OA 形态已渲染（.phone.oa-mode 生效）",
            page.eval_on_selector(".phone", "el => el.classList.contains('oa-mode')") is True)
        chk("G2 判定函数已可从外部驱动（自检暴露生效）",
            page.evaluate("() => typeof window.oaMaybeProjectAction") == "function")

        # 每次都从干净副本出发：断言「弹层数」前先记基线，避免把已有 DOM 当新弹的
        def reset_actions():
            page.evaluate("() => { document.querySelectorAll('.notif-mask').forEach(function (n) { n.remove(); }); }")

        seen_chooser = []
        page.on("filechooser", lambda fc: (seen_chooser.append(1), fc.set_files([])))

        # ---------------------------------------------------------- ① 不在项目内
        reset_actions()
        page.evaluate("() => { window.oaState.currentProject = null; }")
        page.evaluate("() => { document.getElementById('oaDockList').innerHTML = ''; }")
        page.evaluate("() => window.oaMaybeProjectAction({ action: 'REPORT_EXPENSE' })")
        page.wait_for_timeout(250)
        base = page.locator(".notif-mask").count()
        chk("G3 ★不在项目内：不弹花费窗口（不得把花费记到无归属处）", base == 0, "notif-mask count=%d" % base)
        chk("G4 ★不在项目内：给出「先进入项目」的提示（不静默吞掉）",
            "请先在" in dock_text(page) and "项目" in dock_text(page), dock_text(page)[:200])

        # ---------------------------------------------------------- ② 上报花费
        reset_actions()
        page.evaluate("() => { window.oaState.currentProject = { id: 7, name: '弹窗验证项目', projectType: 'BIZ', status: 'ACTIVE' }; }")
        page.evaluate("() => { document.getElementById('oaDockList').innerHTML = ''; }")
        before = page.locator(".notif-mask").count()
        ok_ret = page.evaluate("() => window.oaMaybeProjectAction({ action: 'REPORT_EXPENSE' })")
        page.wait_for_timeout(250)
        n_mask = page.locator(".notif-mask").count()
        chk("G5 ★REPORT_EXPENSE：判定返回 true 且真的弹出了花费表单（新增 1 层，基线 %d）" % before,
            ok_ret is True and before == 0 and n_mask == 1, "ret=%s before=%d n=%d" % (ok_ret, before, n_mask))
        chk("G6 ★弹出的表单字段齐（金额输入 #expAmt 在，方向/分类/日期/备注同源）",
            page.locator(".notif-mask #expAmt").count() == 1
            and page.locator(".notif-mask #expDir").count() == 1
            and page.locator(".notif-mask #expCat").count() == 1
            and page.locator(".notif-mask #expDate").count() == 1)
        chk("G7 ★先在正文里说明再弹窗（对话式，不是凭空弹出）",
            "花费上报窗口" in dock_text(page) and "弹窗验证项目" in dock_text(page), dock_text(page)[:200])

        # ---------------------------------------------------------- ③ 上传文件
        reset_actions()
        page.evaluate("() => { document.getElementById('oaDockList').innerHTML = ''; }")
        seen_chooser.clear()
        # 打桩：本哨兵走 file://、无后端，/docs/tree 必失败 ⇒ `#upFile` 永远 disabled、G9c 点不动。
        # 故在打开上传窗之前劫持 API.req：只把 /docs/tree 解析成「根文件夹已读到」，让产品代码自身的
        # 「取到文件夹后才放开文件控件」逻辑正常走完（inp.disabled=false）。桩只劫持 tree 路径，
        # 其余请求仍走原实现，不影响 G3–G11 其它断言。
        page.evaluate("""() => {
          if (!window.__oaOrigReq) { window.__oaOrigReq = API.req.bind(API); }
          API.req = function(path, opts){
            if (String(path).indexOf('/docs/tree') >= 0) {
              return Promise.resolve({ project: [ { id: 1, name: '项目文档', children: [] } ] });
            }
            return window.__oaOrigReq(path, opts);
          };
        }""")
        before_up = page.locator(".notif-mask").count()
        ok_up = page.evaluate("() => window.oaMaybeProjectAction({ action: 'UPLOAD_FILE' })")
        page.wait_for_timeout(400)
        n_up = page.locator(".notif-mask").count()
        up_file = page.locator(".notif-mask #upFile").count()
        head_txt = page.locator(".notif-mask .notif-head").first.inner_text().strip() if n_up > 0 else ""
        chk("G8 ★UPLOAD_FILE：判定返回 true，正文说明「打开文件上传窗口」",
            ok_up is True and "文件上传窗口" in dock_text(page) and "弹窗验证项目" in dock_text(page),
            "ret=%s dock=%s" % (ok_up, dock_text(page)[:200]))
        chk("G9a ★UPLOAD_FILE：弹出可见上传窗口（新增恰好 1 层、含 #upFile、标题「上传项目文档」）",
            ok_up is True and n_up == before_up + 1 and up_file == 1 and head_txt == "上传项目文档",
            "ret=%s before=%d n=%d upFile=%d head=%r" % (ok_up, before_up, n_up, up_file, head_txt))
        # G9b ★：弹窗那一刻**不**自动唤起文件选择器；这一条正是旧缺陷的定点判据
        # （旧实现会在 await 之后才 inp.click()，被浏览器手势策略静默忽略；若有人改回延迟 click()，这里会立刻触发）
        chk("G9b ★弹窗那一刻不自动唤起文件选择器（旧延迟 click() 才会立刻触发，可抓回退）",
            len(seen_chooser) == 0,
            "filechooser 事件数=%d" % len(seen_chooser))
        # G9c：等「取到文件夹、文件控件被解锁（!disabled）」后，真实点击 #upFile，
        # 选择器才被唤起（入口可用，非空壳控件）。无后端环境靠上面的桩走完解锁逻辑。
        page.wait_for_function(
            "() => { var el=document.querySelector('.notif-mask #upFile'); return !!el && !el.disabled; }",
            timeout=8000)
        folder_sel = page.locator(".notif-mask #upFolder").evaluate(
            "el => { var o = el.selectedOptions && el.selectedOptions[0]; return o ? (o.value + '|' + o.text) : ''; }")
        chk("G9d ★桩生效：#upFolder 已加载文件夹（selectedOptions 非空且含「项目文档」，证明控件真被解锁）",
            folder_sel != "" and "项目文档" in folder_sel,
            "upFolder selected=%r" % folder_sel)
        seen_chooser.clear()
        page.locator(".notif-mask #upFile").click()
        page.wait_for_timeout(200)
        chk("G9c ★点击窗口内 #upFile 才唤起选择器（入口可用、不是空壳控件）",
            len(seen_chooser) >= 1,
            "filechooser 事件数=%d" % len(seen_chooser))
        # 还原 API.req 劫持（桩只影响 tree 路径；还原以保持后续断言环境干净）
        page.evaluate("() => { if (window.__oaOrigReq) API.req = window.__oaOrigReq; }")

        # ---------------------------------------------------------- ④ 负向：无动作
        reset_actions()
        page.evaluate("() => { document.getElementById('oaDockList').innerHTML = ''; }")
        seen_chooser.clear()
        r_none = page.evaluate("() => window.oaMaybeProjectAction({ action: null })")
        r_undef = page.evaluate("() => window.oaMaybeProjectAction({})")
        r_null = page.evaluate("() => window.oaMaybeProjectAction(null)")
        page.wait_for_timeout(250)
        chk("G10 ★负向对照：action 为 null/缺失时**既不弹窗也不说话**（证明 G3–G9 非恒真）",
            page.locator(".notif-mask").count() == 0 and dock_text(page).strip() == ""
            and len(seen_chooser) == 0 and r_none is False and r_undef is False and r_null is False,
            "mask=%d dock=%r chooser=%d" % (page.locator(".notif-mask").count(), dock_text(page)[:80], len(seen_chooser)))

        # ---------------------------------------------------------- ⑤ 未知动作
        reset_actions()
        page.evaluate("() => window.oaMaybeProjectAction({ action: 'SOMETHING_ELSE' })")
        page.wait_for_timeout(200)
        chk("G11 未知动作码：什么都不做（不误开窗）",
            page.locator(".notif-mask").count() == 0, "mask=%d" % page.locator(".notif-mask").count())

        browser.close()

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
