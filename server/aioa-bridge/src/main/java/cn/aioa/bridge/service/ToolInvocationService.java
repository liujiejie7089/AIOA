package cn.aioa.bridge.service;

import cn.aioa.bridge.entity.ToolDefinition;
import cn.aioa.bridge.entity.ToolInvocationLog;
import cn.aioa.bridge.mapper.ToolInvocationLogMapper;
import cn.aioa.bridge.support.ToolApprovalGateway;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.trace.TraceId;
import cn.aioa.security.AuthUser;
import cn.aioa.tool.sdk.LocalToolRegistry;
import cn.aioa.tool.sdk.ToolCallContext;
import cn.aioa.tool.sdk.ToolSpec;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工具调用编排：一次调用要穿过的全部闸门与落账。
 *
 * <p>顺序是刻意固定的，每一步都对应一条治理规则：</p>
 * <ol>
 *   <li><b>解析定义</b>（{@code tool_definition} + {@code tool_system}）—— 未知工具直接 404；</li>
 *   <li><b>权限闸门</b>（{@code tool_permission}）—— 被拒<b>照样落日志</b>，
 *       否则「谁试图调过什么」在审计里查不到；</li>
 *   <li><b>幂等闸门</b> —— 要求幂等的工具没带键 = 拒绝；带了键且已调用过 = 回放首次结果，
 *       保证外部系统的副作用只发生一次；</li>
 *   <li><b>审批闸门</b>（{@code requires_approval}）—— 先落一行 {@code PENDING_APPROVAL}
 *       把入参存下来，再提交审批单；终审通过后由 {@link #resume} 取回该行继续执行；</li>
 *   <li><b>真实调用</b> + 结果落账。</li>
 * </ol>
 *
 * <p><b>不吞异常</b>：闸门判定为「拒」是正常业务结果（返回 ok=false + 原因，不抛异常，
 * 让调用方/模型能读懂并改条件）；只有「工具不存在」这种配置性问题才 404。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolInvocationService {

    /** 幂等键也可从入参里取，兼容「模型只会在 parameters 里给字段」的场景。 */
    private static final String ARG_IDEMPOTENCY_KEY = "idempotencyKey";
    /** 明显的敏感键名（值不落审计）。 */
    private static final List<String> SENSITIVE_HINTS =
            List.of("password", "passwd", "secret", "token", "apikey", "api_key", "credential");

    private final ToolRegistryService registry;
    private final ToolPermissionService permission;
    private final ToolDispatcher dispatcher;
    private final ToolInvocationLogMapper logMapper;
    private final ObjectProvider<ToolApprovalGateway> approvalGateway;
    /** 服务内（{@code local://}）工具注册表：注解声明的工具在此直接反射执行，不出网。 */
    private final LocalToolRegistry localTools;
    private final ObjectMapper objectMapper;

    // ================================================================== 调用

    /**
     * 执行一次工具调用。
     *
     * @param idempotencyKey 幂等键（可空；{@code args.idempotencyKey} 亦可）
     * @param user           调用者（服务间调用时由调用方显式传递，见 InternalToolController）
     */
    public Map<String, Object> invoke(String toolCode, String version, String runId,
                                      Map<String, Object> args, String idempotencyKey, AuthUser user) {
        long tenantId = tenantOf(user);
        Long userId = user == null ? null : user.getUserId();
        Map<String, Object> in = args == null ? new LinkedHashMap<>() : new LinkedHashMap<>(args);
        String key = resolveIdempotencyKey(idempotencyKey, in);

        ToolRegistryService.Resolved resolved = registry.resolve(tenantId, toolCode, version);
        ToolDefinition def = resolved.definition();

        // ---- ② 权限闸门 -------------------------------------------------
        List<String> roles = user == null || user.getRoles() == null ? List.of() : user.getRoles();
        ToolPermissionService.Decision decision = permission.check(tenantId, def.getToolCode(), roles);
        if (!decision.allowed()) {
            Long id = logDenied(tenantId, def, runId, userId, in, key,
                    ToolInvocationLog.ERROR_PERMISSION_DENIED, decision.reason());
            Map<String, Object> out = resp(false, "DENIED");
            out.put("error", decision.reason());
            out.put("invocationId", id);
            return out;
        }

        // ---- ③ 幂等闸门 -------------------------------------------------
        if (Boolean.TRUE.equals(def.getIdempotencyRequired())
                && (key == null || key.isBlank())) {
            String msg = "该工具要求幂等键：请在 idempotencyKey 传入唯一调用号"
                    + "（也可放在 args.idempotencyKey）";
            Long id = logDenied(tenantId, def, runId, userId, in, key, "IDEMPOTENCY_KEY_REQUIRED", msg);
            Map<String, Object> out = resp(false, "ERROR");
            out.put("error", msg);
            out.put("invocationId", id);
            return out;
        }
        if (key != null && !key.isBlank()) {
            ToolInvocationLog prev = findByIdem(tenantId, def.getToolCode(), key);
            if (prev != null && !ToolInvocationLog.ERROR_PENDING_APPROVAL.equals(prev.getErrorCode())) {
                Map<String, Object> out = resp(true, "DEDUPED");
                out.put("deduped", true);
                // 回放必须与首次调用**同形**：同样过一遍 response_jmespath，
                // 否则「重放的 data 是整包、首次的 data 是字段」——调用方无法把两者
                // 当作同一件事处理，幂等就只幂等了副作用、没幂等语义。
                out.put("data", dispatcher.extract(prev.getResultBody(), def.getResponseJmespath()));
                out.put("httpStatus", prev.getHttpStatus());
                out.put("invocationId", prev.getId());
                out.put("message", "同幂等键已调用过，直接回放首次结果（未重复触发外部调用）");
                return out;
            }
        }

        // ---- ④ 审批闸门 -------------------------------------------------
        if (Boolean.TRUE.equals(def.getRequiresApproval())) {
            return submitForApproval(tenantId, def, version, runId, userId, in, key, user);
        }

        // ---- ⑤ 真实调用（出网 HTTP 或服务内反射，二选一）-----------------
        Long logId = persist(tenantId, def, runId, userId, in, key, null, null);
        return dispatchAndFinalize(def, resolved.system(), in, user, logId);
    }

    /** 挂起并提交审批：返回 PENDING_APPROVAL（不入队、不执行）。 */
    private Map<String, Object> submitForApproval(long tenantId, ToolDefinition def, String version,
                                                  String runId, Long userId, Map<String, Object> in,
                                                  String key, AuthUser user) {
        ToolApprovalGateway gateway = approvalGateway.getIfAvailable();
        if (gateway == null) {
            String msg = "工具「" + def.getToolCode() + "」需审批，但审批网关未装配"
                    + "（缺少 ToolApprovalGateway 实现），已拒绝执行";
            log.error(msg);
            Long id = logDenied(tenantId, def, runId, userId, in, key, "APPROVAL_GATEWAY_MISSING", msg);
            Map<String, Object> out = resp(false, "ERROR");
            out.put("error", msg);
            out.put("invocationId", id);
            return out;
        }
        Long logId = persist(tenantId, def, runId, userId, in, key,
                ToolInvocationLog.ERROR_PENDING_APPROVAL, null);
        String title = "工具调用审批：" + (def.getName() == null ? def.getToolCode() : def.getName());
        Long orderId;
        try {
            orderId = gateway.submit(new ToolApprovalGateway.ApprovalRequest(
                    tenantId, user, def.getToolCode(), version, title, in, logId));
        } catch (RuntimeException e) {
            String msg = "提交审批失败：" + e.getMessage();
            log.warn("工具审批提交失败：tool={}, logId={}", def.getToolCode(), logId, e);
            updateLog(logId, w -> w.set(ToolInvocationLog::getErrorCode, "APPROVAL_SUBMIT_FAILED"));
            Map<String, Object> out = resp(false, "ERROR");
            out.put("error", msg);
            out.put("invocationId", logId);
            return out;
        }
        if (orderId == null) {
            updateLog(logId, w -> w.set(ToolInvocationLog::getErrorCode, "APPROVAL_SUBMIT_FAILED"));
            Map<String, Object> out = resp(false, "ERROR");
            out.put("error", "提交审批失败：审批网关未返回审批单号");
            out.put("invocationId", logId);
            return out;
        }
        final String approvalId = String.valueOf(orderId);
        updateLog(logId, w -> w.set(ToolInvocationLog::getApprovalId, approvalId));
        Map<String, Object> out = resp(true, "PENDING_APPROVAL");
        out.put("approvalOrderId", orderId);
        out.put("approvalId", approvalId);
        out.put("invocationId", logId);
        out.put("toolCode", def.getToolCode());
        out.put("message", "该工具需审批：已提交审批单 #" + orderId + "，终审通过后自动执行，无需再次调用");
        return out;
    }

    // ================================================================== 恢复 / 终止

    /**
     * 审批通过后恢复执行（由审批终态回调驱动）。
     *
     * <p>幂等：找不到 {@code PENDING_APPROVAL} 行时返回 {@code NOOP}，
     * 因此回调重复触发不会重复调用外部系统。</p>
     */
    public Map<String, Object> resume(String approvalId) {
        if (approvalId == null || approvalId.isBlank()) {
            throw BizException.badRequest("approvalId 不能为空");
        }
        List<ToolInvocationLog> rows = logMapper.selectList(new LambdaQueryWrapper<ToolInvocationLog>()
                .eq(ToolInvocationLog::getApprovalId, approvalId)
                .eq(ToolInvocationLog::getErrorCode, ToolInvocationLog.ERROR_PENDING_APPROVAL)
                .orderByDesc(ToolInvocationLog::getId));
        if (rows.isEmpty()) {
            Map<String, Object> out = resp(true, "NOOP");
            out.put("message", "没有待恢复的工具调用（可能已恢复过或已被驳回）");
            return out;
        }
        ToolInvocationLog row = rows.get(0);
        long tenantId = row.getTenantId() == null ? 0L : row.getTenantId();
        ToolRegistryService.Resolved resolved;
        try {
            resolved = registry.resolve(tenantId, row.getToolCode(), row.getVersion());
        } catch (BizException e) {
            updateLog(row.getId(), w -> w.set(ToolInvocationLog::getErrorCode, "TOOL_GONE_AFTER_APPROVAL"));
            Map<String, Object> out = resp(false, "ERROR");
            out.put("error", "审批通过但工具已不可用：" + e.getMessage());
            out.put("invocationId", row.getId());
            return out;
        }
        Map<String, Object> in = row.getPendingArgs() == null
                ? new LinkedHashMap<>() : new LinkedHashMap<>(row.getPendingArgs());
        // 恢复执行时只知道原调用者 id：本地工具需要调用者上下文，用最小可用身份注入
        // （权限闸门在提交审批前已经过了，这里不重复判定，但也不能凭空造出角色）。
        AuthUser caller = AuthUser.builder()
                .tenantId(tenantId)
                .userId(row.getUserId())
                .username("resumed-by-approval")
                .roles(List.of())
                .permissions(List.of())
                .build();
        Map<String, Object> out = dispatchAndFinalize(resolved.definition(), resolved.system(), in, caller, row.getId());
        out.put("resumedFromApproval", approvalId);
        return out;
    }

    /** 审批驳回：把挂起的调用标记为终止（不再执行）。 */
    public Map<String, Object> abort(String approvalId, String reason) {
        if (approvalId == null || approvalId.isBlank()) {
            return Map.of("ok", true, "status", "NOOP", "message", "approvalId 为空，忽略");
        }
        List<ToolInvocationLog> rows = logMapper.selectList(new LambdaQueryWrapper<ToolInvocationLog>()
                .eq(ToolInvocationLog::getApprovalId, approvalId)
                .eq(ToolInvocationLog::getErrorCode, ToolInvocationLog.ERROR_PENDING_APPROVAL));
        for (ToolInvocationLog row : rows) {
            updateLog(row.getId(), w -> w.set(ToolInvocationLog::getErrorCode, "APPROVAL_REJECTED"));
        }
        Map<String, Object> out = resp(true, rows.isEmpty() ? "NOOP" : "ABORTED");
        out.put("aborted", rows.size());
        if (reason != null) {
            out.put("reason", reason);
        }
        return out;
    }

    // ================================================================== 清单

    /**
     * 供智能体注入模型的工具清单（OpenAI function 格式），已按调用者角色过滤。
     *
     * <p>过滤发生在服务端而不是提示词里：把无权调用的工具暴露给模型，
     * 只会换来一次次「调用被拒绝」的无效轮次。</p>
     */
    public List<Map<String, Object>> catalog(Long tenantId, List<String> roles) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (ToolDefinition def : registry.catalog(tenantId)) {
            if (!permission.check(tenantId, def.getToolCode(), roles).allowed()) {
                continue;
            }
            Map<String, Object> fn = new LinkedHashMap<>();
            fn.put("name", def.getToolCode());
            fn.put("description", def.getDescription() == null ? def.getName() : def.getDescription());
            fn.put("parameters", def.getInputSchema() == null
                    ? Map.of("type", "object", "properties", Map.of())
                    : def.getInputSchema());
            Map<String, Object> tool = new LinkedHashMap<>();
            tool.put("type", "function");
            tool.put("function", fn);
            tool.put("x-aioa-version", def.getVersion());
            tool.put("x-aioa-risk", def.getRiskLevel());
            tool.put("x-aioa-requires-approval", Boolean.TRUE.equals(def.getRequiresApproval()));
            out.add(tool);
        }
        return out;
    }

    // ================================================================== 内部

    /** 落一行日志（新建调用）。 */
    private Long persist(long tenantId, ToolDefinition def, String runId, Long userId,
                         Map<String, Object> in, String key, String errorCode, String approvalId) {
        ToolInvocationLog row = new ToolInvocationLog();
        row.setTenantId(tenantId);
        row.setTraceId(TraceId.get());
        row.setRunId(runId);
        row.setToolCode(def.getToolCode());
        row.setVersion(def.getVersion());
        row.setUserId(userId);
        row.setArgsMasked(mask(in));
        row.setPendingArgs(new LinkedHashMap<>(in));
        row.setIdempotencyKey(blankToNull(key));
        row.setApprovalId(approvalId);
        row.setErrorCode(errorCode);
        row.setCreatedAt(LocalDateTime.now());
        logMapper.insert(row);
        return row.getId();
    }

    /** 被闸门拒绝也落日志：审计要能回答「谁试图调过什么、为什么没成」。 */
    private Long logDenied(long tenantId, ToolDefinition def, String runId, Long userId,
                           Map<String, Object> in, String key, String errorCode, String reason) {
        Long id = persist(tenantId, def, runId, userId, in, key, errorCode, null);
        if (reason != null) {
            log.info("工具调用被拒：tool={}, code={}, reason={}", def.getToolCode(), errorCode, reason);
        }
        return id;
    }

    private void finalize(Long logId, ToolDispatcher.Outcome outcome) {
        String err = outcome.ok() ? null
                : (outcome.error() != null ? "NETWORK_ERROR" : "HTTP_" + outcome.httpStatus());
        String body = outcome.body();
        updateLog(logId, w -> w
                .set(ToolInvocationLog::getHttpStatus, outcome.httpStatus())
                .set(ToolInvocationLog::getDurationMs, outcome.durationMs())
                .set(ToolInvocationLog::getResultSize, body == null ? null : (long) body.length())
                .set(ToolInvocationLog::getResultDigest, ToolDispatcher.digest(body))
                .set(ToolInvocationLog::getResultBody, body)
                .set(ToolInvocationLog::getErrorCode, err));
    }

    /**
     * 最后一跳：按定义选择「出网 HTTP」或「服务内反射」，并统一落账与返回体。
     *
     * <p>两条通路共用同一套信封（{@code ok/status/data|error/httpStatus}），
     * 因此上层（模型 / 调用方）不需要知道某工具是本地实现还是远程系统。</p>
     */
    private Map<String, Object> dispatchAndFinalize(ToolDefinition def, cn.aioa.bridge.entity.ToolSystem system,
                                                    Map<String, Object> in, AuthUser user, Long logId) {
        if (ToolSpec.isLocal(def.getEndpoint())) {
            return localDispatch(def, in, user, logId);
        }
        ToolDispatcher.Outcome outcome = dispatcher.call(def, system, in);
        finalize(logId, outcome);
        return dispatchResult(outcome, def, logId);
    }

    /**
     * 服务内工具执行。
     *
     * <p><b>为什么本地调用也写 httpStatus</b>：它没有真实 HTTP 状态码，
     * 但下游（幂等回放、失败归因、监控）只认这一列。用 200 / 500 表达
     * 「通路成功 / 业务失败」，语义上等价于「一次调用的成败」，避免再多一条分支。
     * {@code endpoint} 的 {@code local://} 前缀才是「这是本地工具」的权威判据。</p>
     */
    private Map<String, Object> localDispatch(ToolDefinition def, Map<String, Object> in,
                                              AuthUser user, Long logId) {
        long start = System.currentTimeMillis();
        try {
            Object result = localTools.invoke(def.getToolCode(), in, toContext(user));
            long cost = System.currentTimeMillis() - start;
            String body = toJson(result);
            updateLog(logId, w -> w
                    .set(ToolInvocationLog::getHttpStatus, 200)
                    .set(ToolInvocationLog::getDurationMs, cost)
                    .set(ToolInvocationLog::getResultSize, body == null ? null : (long) body.length())
                    .set(ToolInvocationLog::getResultDigest, ToolDispatcher.digest(body))
                    .set(ToolInvocationLog::getResultBody, body)
                    .set(ToolInvocationLog::getErrorCode, null));

            Map<String, Object> inner = result instanceof Map<?, ?> m ? castMap(m) : null;
            Map<String, Object> out = resp(true, "OK");
            out.put("invocationId", logId);
            out.put("toolCode", def.getToolCode());
            out.put("httpStatus", 200);
            out.put("durationMs", cost);
            out.put("local", true);
            // 工具自己返回 {ok:false,error} 时，外层如实转达 ——
            // 「通路成功」与「业务成功」是两件事，不能因为没抛异常就报成功。
            if (inner != null && inner.containsKey("ok")) {
                boolean bizOk = Boolean.TRUE.equals(inner.get("ok"));
                out.put("ok", bizOk);
                out.put("status", bizOk ? "OK" : "ERROR");
                out.put("data", inner.get("data"));
                if (!bizOk) {
                    out.put("error", inner.get("error"));
                }
            } else {
                out.put("data", result);
            }
            return out;
        } catch (RuntimeException e) {
            long cost = System.currentTimeMillis() - start;
            log.warn("服务内工具执行失败：tool={}, logId={}", def.getToolCode(), logId, e);
            updateLog(logId, w -> w
                    .set(ToolInvocationLog::getHttpStatus, 500)
                    .set(ToolInvocationLog::getDurationMs, cost)
                    .set(ToolInvocationLog::getErrorCode, "LOCAL_ERROR"));
            Map<String, Object> out = resp(false, "ERROR");
            out.put("invocationId", logId);
            out.put("toolCode", def.getToolCode());
            out.put("httpStatus", 500);
            out.put("local", true);
            out.put("error", e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            return out;
        }
    }

    private static ToolCallContext toContext(AuthUser user) {
        if (user == null) {
            return ToolCallContext.system();
        }
        return new ToolCallContext(user.getTenantId(), user.getUserId(), user.getUsername(),
                user.getInstitutionId(), user.getRoles() == null ? List.of() : user.getRoles());
    }

    private static Map<String, Object> castMap(Map<?, ?> raw) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<?, ?> e : raw.entrySet()) {
            out.put(String.valueOf(e.getKey()), e.getValue());
        }
        return out;
    }

    private String toJson(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return String.valueOf(value);
        }
    }

    private void updateLog(Long logId, java.util.function.Consumer<LambdaUpdateWrapper<ToolInvocationLog>> mutator) {
        LambdaUpdateWrapper<ToolInvocationLog> w = Wrappers.lambdaUpdate(ToolInvocationLog.class)
                .eq(ToolInvocationLog::getId, logId);
        mutator.accept(w);
        logMapper.update(null, w);
    }

    private Map<String, Object> dispatchResult(ToolDispatcher.Outcome outcome, ToolDefinition def, Long logId) {
        Map<String, Object> out = resp(outcome.ok(), outcome.ok() ? "OK" : "ERROR");
        out.put("invocationId", logId);
        out.put("toolCode", def.getToolCode());
        out.put("httpStatus", outcome.httpStatus());
        out.put("durationMs", outcome.durationMs());
        if (outcome.ok()) {
            out.put("data", dispatcher.extract(outcome.body(), def.getResponseJmespath()));
        } else {
            out.put("error", outcome.error() != null ? outcome.error()
                    : "外部系统返回 HTTP " + outcome.httpStatus());
        }
        return out;
    }

    private ToolInvocationLog findByIdem(long tenantId, String toolCode, String key) {
        List<ToolInvocationLog> rows = logMapper.selectList(new LambdaQueryWrapper<ToolInvocationLog>()
                .eq(ToolInvocationLog::getTenantId, tenantId)
                .eq(ToolInvocationLog::getToolCode, toolCode)
                .eq(ToolInvocationLog::getIdempotencyKey, key)
                .orderByAsc(ToolInvocationLog::getId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 响应体回放：{@code status=DEDUPED} 时复用首次调用的响应体与裁剪口径。 */
    private static Map<String, Object> resp(boolean ok, String status) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", ok);
        m.put("status", status);
        m.put("traceId", TraceId.get());
        return m;
    }

    private static String resolveIdempotencyKey(String explicit, Map<String, Object> args) {
        if (explicit != null && !explicit.isBlank()) {
            return explicit;
        }
        Object fromArgs = args.get(ARG_IDEMPOTENCY_KEY);
        return fromArgs == null ? null : String.valueOf(fromArgs);
    }

    private static long tenantOf(AuthUser user) {
        return user == null || user.getTenantId() == null ? 0L : user.getTenantId();
    }

    private static String blankToNull(String v) {
        return v == null || v.isBlank() ? null : v;
    }

    /** 入参脱敏拷贝：敏感键的值替换为 ***（仅用于审计展示，不影响重放）。 */
    static Map<String, Object> mask(Map<String, Object> in) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (in == null) {
            return out;
        }
        for (Map.Entry<String, Object> e : in.entrySet()) {
            out.put(e.getKey(), isSensitive(e.getKey()) && e.getValue() != null ? "***" : e.getValue());
        }
        return out;
    }

    private static boolean isSensitive(String key) {
        if (key == null) {
            return false;
        }
        String k = key.toLowerCase(java.util.Locale.ROOT).replace("-", "").replace("_", "");
        Set<String> hints = new HashSet<>(SENSITIVE_HINTS);
        for (String h : hints) {
            if (k.contains(h.replace("_", ""))) {
                return true;
            }
        }
        return false;
    }
}
