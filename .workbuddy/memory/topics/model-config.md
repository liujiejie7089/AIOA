# 模型管理（管理端「手动添加模型」· V61）

> 入口：管理端 → 平台管理员 → 模型管理。接口基址 `/api/v1/admin/models`（仅 `ROLE_ADMIN`）。
> 当前系统默认模型 = **MiniMax**（`MiniMax-Text-01` @ `https://api.minimax.chat/v1`）。

## 数据与字段
- 表 `model_config`：V13 建表（provider_key / name / base_url / model_name / api_key_env / enabled /
  is_default / sort），**V61** 扩 `provider_type` / `api_key`(密文) / `temperature` / `max_context`。
- 大模型类型预设由 `ModelConfigService.PRESETS` 提供（minimax / deepseek / dashscope / vllm / ollama /
  echo / custom），前端 `GET /admin/models/presets` 拿，**不在前端另抄一份**。

## 接口
| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/admin/models` | 列表（**只回掩码** `apiKeyMasked` + `apiKeySource`） |
| GET | `/admin/models/presets` | 类型预设 + `keyEncryptionWeak` |
| POST / PUT | `/admin/models`[/{key}] | 新增 / 编辑，保存后推送 agent 热加载 |
| PUT | `/admin/models/{key}/status` | 启停，**启用前先校验**，不通过抛业务错误且保持停用 |
| POST | `/admin/models/{key}/test` | 只校验，不改状态 |
| PUT | `/admin/models/{key}/default` · DELETE | 设默认 · 删除（默认模型不可删） |

## 铁律（易回退）
1. **连通性校验委托 agent**（`POST /internal/v1/models/check`），不在服务端直连供应商——
   服务端容器通常没有供应商 Key，直连会把「本进程没配 Key」误报成「模型连不通」。校验前先 `push()`。
2. **密钥来源判定以运行时为准**：`apiKeySource` = DB（管理端填写）> 本进程环境变量 >
   agent 侧 `api_key_configured=yes`。三者都没有才是 NONE（否则显示「未配置」是假话）。
3. **掩码往返保护**：列表只回掩码，编辑保存会原样回传 → 服务端遇到含 `****` 的值必须**保持库里密文不变**，
   否则真实密钥被覆盖成 `****`。
4. **agent 侧「禁用集合」与「规格注册」解耦**：`apply_overrides` 遇 `enabled=false` 也要注册规格，
   否则「保存（停用）→ 点启动」会因模型未注册而永远失败。下发是全量的，不在列表且非内置键 = 已删除，要清规格+内存 Key。
5. `apiKey` 落库用 `ModelKeyCodec`（AES-256-GCM），密钥 `AIOA_MODEL_KEY_ENC_KEY` →
   `AIOA_GITEE_TOKEN_ENC_KEY` → 内置（启动 WARN，生产必须配）。**明文只出现在保存请求体与推送 agent 的内网链路**。

## 调用链路一致性的落点
- 温度：专家配置（`expert_settings.temperature`）> 模型配置（`provider.temperature`）> 0.3。
- 最大上下文：`_build_messages(req, max_context)` 按字符预算裁剪多轮历史，**0 = 不限制**（保持既有行为）。
  `/internal/v1/complete` 的 `req.max_tokens` 原来被写进一个**没发出的** body（死代码），已改为真正下发。
