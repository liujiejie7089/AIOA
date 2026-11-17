# Bug Test Report: AIOA 全项目审查 18 项

- **Slug**: full-audit-2026-11-17
- **Date**: 2026-11-17T19:32:00+08:00
- **Verdict**: **verified**（17 项已修并验证；1 项 L3 判定误报、不修）

## 验证手段与证据

| 项 | 验证方式 | 结果 |
|---|---|---|
| C1 | 临时脚本实跑 `_validate_ast`/`run_script` + 单测 `test_sandbox_blocks_getattr_and_string_dunder` | `getattr((),'__class__')`、`d='__globals__'`、`hasattr(...'__bases__')`、别名调用全部 `ok=False`；良性 `40+2` 正常 |
| H4 | 临时脚本 `_assert_public_url` + 单测 `test_web_fetch_rejects_private_and_metadata_hosts` | 127.0.0.1 / 169.254.169.254 / 10.0.0.5 / [::1] / file:// 全 BLOCK；example.com ALLOW |
| L2 | 单测 `test_internal_payload_without_trace_never_promises_a_number` + 实跑 | `internal_payload(None)` 文案无「错误编号」且无 errorId；`internal_payload("run-123")` 两者齐全 |
| H1 | Java 单测 `SqlQueryToolTenantTest`（4 项，反射调 private） | 自带 `tenant_id>0` 仍叠加当前租户；无 WHERE 追加；ORDER BY 前插入；别名前缀。4/4 通过 |
| M1 | 静态核对 + Java 编译 | 两处 catch 已无 `e.getMessage()` 外发；编译通过 |
| H2 | 静态核对 + Java 编译 | download 用三条件联合查询；编译通过 |
| L1 | 静态核对 + Java 编译 | `Math.min(...,200)` 就位 |
| M2 | Java 全量单测（含新 mapper 方法编译） | 批量聚合 SQL 编入，DashboardService 归并逻辑编译通过；无测试回归 |
| M3 | 静态核对 + Java 编译 | 日志已无口令占位符 |
| M4 | Java 编译 | `log.warn` 就位，`@Slf4j` 补齐，编译通过 |
| H3 | `scripts/_verify_audit_fixes_h5.py` 静态判据 | escJs 三处就位、safeUrl 拒绝伪协议、附件 rel=noopener。PASS |
| M6 | 同上 | 50MB 上限判据 PASS |
| M7 | 同上 | 非200 信封解析判据 PASS |
| L4 | 同上 | sessionStorage 写入/读回迁移/双清三处判据 PASS |
| L5 | 同上 | encodeURIComponent 判据 PASS |
| L6 | 同上 | rAF 合并 + 防排版回退判据 PASS |
| M5 | 人工核验（vue-tsc 未安装，无法自动类型检查） | 正则 `^\/(?![\/\\])` 挡住 `//evil.com`、`/\evil.com`、`http(s)://`；`/home` 放行 |
| L3 | 回源核验 | `nodes.py:769` 仅打印工具名列表，不含参数 → 判定误报，不改 |

## 汇总回归

| 套件 | 结果 |
|---|---|
| `pytest agent/tests`（全量） | **403 passed**（原 400 + 新增 3 条针对性单测） |
| `mvn -pl aios-resource,aios-org -am test`（全量） | **EXIT=0**，无测试失败；新增 `SqlQueryToolTenantTest` 4/4 通过 |
| `scripts/_verify_audit_fixes_h5.py` | **11/11 PASS**，含两个 script 块 `node --check` 全通过 |
| `scripts/_verify_audit_fixes_py.py`（临时实跑探针） | C1/H4/L2 三项现场复现+修复确认全通过 |

## 已知验证缺口（如实列出，不伪装覆盖）

1. **管理端 M5 无自动类型检查**：`web/node_modules` 里未安装 `vue-tsc`，无法跑 `vue-tsc --noEmit`；改动是一行正则的纯 JS 逻辑，已人工核验。
2. **Java 改动未做真机 HTTP 端到端**：改了 FileController/SqlQueryToolService 等运行时行为，但本次只做编译+单测级验证，未启动 8080 后端跑真机接口（服务当前全部停止）。需要真机验证的语义：H2 越权下载返回 404、H1 跨租户 SQL 结果为空。
3. **H5 改动为静态判据+语法检查**：未用浏览器自动化点击验证运行时行为（如 XSS 载荷实际不执行、rAF 流式显示正常）。判据已覆盖源码形态，行为级需人工在页面确认。
4. **默认模型通道额度**：本轮未触发 agent 真机 LLM 调用，不受额度影响。

以上缺口不影响 verdict=verified 的判定依据——所有 18 项的**修复本身**都通过了对应层级的验证（单测/静态判据/实跑探针）；缺口属于"更高层级的端到端验证未做"，不是"修复未验证"。

## 下一步（可选，非本次交付范围）

- 若需最高置信度：启动 8080 后端，用两租户账号实测 H1/H2 的跨租户/越权返回；用浏览器实测 H3 的 `' 闭合载荷不执行脚本。
