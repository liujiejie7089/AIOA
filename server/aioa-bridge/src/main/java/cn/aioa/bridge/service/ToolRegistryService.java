package cn.aioa.bridge.service;

import cn.aioa.bridge.entity.ToolDefinition;
import cn.aioa.bridge.entity.ToolSystem;
import cn.aioa.bridge.mapper.ToolDefinitionMapper;
import cn.aioa.bridge.mapper.ToolSystemMapper;
import cn.aioa.common.exception.BizException;
import cn.aioa.tool.sdk.LocalToolRegistry;
import cn.aioa.tool.sdk.ToolSpec;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 工具注册表：把「定义驱动」落到查询上。
 *
 * <p>桥接的全部行为都从 {@code tool_definition} / {@code tool_system} 读出来，
 * 不在代码里写任何工具白名单 —— 加一个工具 = 加一行数据，不改代码、不重新发版。</p>
 *
 * <p><b>作用域优先级</b>：租户专享定义 &gt; 平台级定义（{@code tenant_id=0}）。
 * 与 docs/16「组织作用域」的既有口径一致：越具体的作用域越优先。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolRegistryService {

    /** 平台级定义 / 业务系统的租户占位值。 */
    public static final long GLOBAL_TENANT_ID = 0L;

    private final ToolDefinitionMapper definitionMapper;
    private final ToolSystemMapper systemMapper;
    /** 进程内工具（{@code @AioaTool} 声明）：作为定义表的兜底来源，见 {@link #sdkDefinition}。 */
    private final LocalToolRegistry localTools;

    /** 解析结果：可执行的定义 + 它所属的业务系统（系统可为 null，此时 endpoint 必须是绝对地址）。 */
    public record Resolved(ToolDefinition definition, ToolSystem system) {
    }

    /**
     * 解析一个可执行的工具定义。
     *
     * @param version 指定版本；null / 空 = 取作用域内的最高版本
     * @throws BizException 工具不存在、已停用或指定版本缺失（404 语义，不泄露其它租户的存在性）
     */
    public Resolved resolve(Long tenantId, String toolCode, String version) {
        if (toolCode == null || toolCode.isBlank()) {
            throw BizException.badRequest("toolCode 不能为空");
        }
        long tid = nz(tenantId);
        List<ToolDefinition> all = definitionMapper.selectList(new LambdaQueryWrapper<ToolDefinition>()
                .eq(ToolDefinition::getToolCode, toolCode)
                .isNull(ToolDefinition::getDeletedAt));
        List<ToolDefinition> active = new ArrayList<>();
        for (ToolDefinition d : all) {
            if (isActive(d)) {
                active.add(d);
            }
        }
        List<ToolDefinition> scoped = filterByTenant(active, tid);
        ToolDefinition def = null;
        if (!scoped.isEmpty()) {
            if (version != null && !version.isBlank()) {
                def = scoped.stream().filter(d -> version.equals(d.getVersion())).findFirst().orElse(null);
            } else {
                def = scoped.stream()
                        .max((a, b) -> compareVersion(s(a.getVersion()), s(b.getVersion())))
                        .orElse(null);
            }
        }
        if (def == null) {
            // 定义表里没有 → 回落到进程内 SDK 声明。
            // 这个兜底不是「容错」，而是必要的：注解声明与落库是两步，
            // 若因任何原因第二步没成功（表被清、迁移未跑、落库异常），
            // 「代码里明明有这个工具却调不通」是最难排查的一类故障。
            ToolDefinition sdk = sdkDefinition(toolCode, version);
            if (sdk != null) {
                return new Resolved(sdk, null);
            }
            throw BizException.notFound("工具不存在或已停用：" + toolCode
                    + (version == null || version.isBlank() ? "" : "（版本 " + version + "）"));
        }
        ToolSystem system = def.getSystemCode() == null || def.getSystemCode().isBlank()
                ? null
                : resolveSystem(tid, def.getSystemCode());
        return new Resolved(def, system);
    }

    /** 用 SDK 声明合成一个「等价定义」（不落库），使注解工具在定义表缺行时依然可调用。 */
    private ToolDefinition sdkDefinition(String toolCode, String version) {
        ToolSpec spec = localTools.get(toolCode);
        if (spec == null) {
            return null;
        }
        if (version != null && !version.isBlank() && !version.equals(spec.version())) {
            return null;
        }
        ToolDefinition d = new ToolDefinition();
        d.setTenantId(GLOBAL_TENANT_ID);
        d.setToolCode(spec.toolCode());
        d.setVersion(spec.version());
        d.setName(spec.displayName());
        d.setDescription(spec.description());
        d.setDomain(spec.domain() == null || spec.domain().isBlank() ? "sdk" : spec.domain());
        d.setSystemCode(spec.systemCode());
        d.setEndpoint(spec.endpoint());
        d.setHttpMethod("LOCAL");
        d.setInputSchema(spec.inputSchema());
        d.setRiskLevel(spec.riskLevel());
        d.setRequiresApproval(spec.requiresApproval());
        d.setIdempotencyRequired(spec.idempotencyRequired());
        d.setStatus("ACTIVE");
        d.setOwner(spec.owner());
        return d;
    }

    /**
     * 已注册工具清单（未做权限过滤，过滤在 {@code ToolInvocationService#catalog}）。
     * 同一 toolCode 只保留优先级最高的那一条（租户专享覆盖平台级）。
     */
    public List<ToolDefinition> catalog(Long tenantId) {
        long tid = nz(tenantId);
        List<ToolDefinition> all = definitionMapper.selectList(new LambdaQueryWrapper<ToolDefinition>()
                .isNull(ToolDefinition::getDeletedAt));
        Map<String, List<ToolDefinition>> byCode = new LinkedHashMap<>();
        for (ToolDefinition d : all) {
            if (isActive(d) && d.getToolCode() != null) {
                byCode.computeIfAbsent(d.getToolCode(), k -> new ArrayList<>()).add(d);
            }
        }
        List<ToolDefinition> out = new ArrayList<>(byCode.size());
        for (List<ToolDefinition> group : byCode.values()) {
            List<ToolDefinition> scoped = filterByTenant(group, tid);
            if (scoped.isEmpty()) {
                continue;
            }
            scoped.stream()
                    .max((a, b) -> compareVersion(s(a.getVersion()), s(b.getVersion())))
                    .ifPresent(out::add);
        }
        // 进程内 SDK 工具补进清单：定义表缺行时清单不能让它们「消失」，
        // 否则模型不知道能调什么，注解声明的价值就断了。
        for (ToolSpec spec : localTools.all()) {
            if (byCode.containsKey(spec.toolCode())) {
                continue;
            }
            ToolDefinition d = sdkDefinition(spec.toolCode(), spec.version());
            if (d != null) {
                out.add(d);
            }
        }
        return out;
    }

    /** 业务系统解析：租户专享 &gt; 平台级；未注册或停用返回 null（由调用方判定是否致命）。 */
    public ToolSystem resolveSystem(Long tenantId, String systemCode) {
        List<ToolSystem> rows = systemMapper.selectList(new LambdaQueryWrapper<ToolSystem>()
                .eq(ToolSystem::getSystemCode, systemCode)
                .isNull(ToolSystem::getDeletedAt));
        List<ToolSystem> active = new ArrayList<>();
        for (ToolSystem s : rows) {
            if (s.getStatus() == null || "ACTIVE".equalsIgnoreCase(s.getStatus())) {
                active.add(s);
            }
        }
        List<ToolSystem> scoped = filterByTenant(active, nz(tenantId));
        if (scoped.isEmpty()) {
            log.warn("业务系统未注册或已停用：systemCode={}, tenantId={}", systemCode, tenantId);
            return null;
        }
        return scoped.get(0);
    }

    /** 作用域过滤：本租户行优先；本租户无行时回落到平台级行。 */
    private static <T> List<T> filterByTenant(List<T> rows, long tenantId) {
        List<T> own = new ArrayList<>();
        List<T> global = new ArrayList<>();
        for (T r : rows) {
            long t = r instanceof ToolDefinition d ? nz(d.getTenantId())
                    : r instanceof ToolSystem s ? nz(s.getTenantId()) : GLOBAL_TENANT_ID;
            if (t == tenantId && tenantId != GLOBAL_TENANT_ID) {
                own.add(r);
            } else if (t == GLOBAL_TENANT_ID) {
                global.add(r);
            }
        }
        return own.isEmpty() ? global : own;
    }

    private static boolean isActive(ToolDefinition d) {
        return d.getStatus() == null || "ACTIVE".equalsIgnoreCase(d.getStatus());
    }

    private static long nz(Long v) {
        return v == null ? GLOBAL_TENANT_ID : v;
    }

    private static String s(String v) {
        return v == null ? "0" : v;
    }

    /**
     * 语义化版本比较（{@code 1.10.0 &gt; 1.9.0}）。
     *
     * <p>刻意不用字符串比较：字典序会把 {@code 1.10.0} 判成小于 {@code 1.9.0}，
     * 于是「取最高版本」会稳定地取到旧版本 —— 这种 bug 只在版本号跨两位数时出现，
     * 很难在演示环境暴露。非数字段按字典序兜底，保证比较关系是全序。</p>
     */
    public static int compareVersion(String a, String b) {
        String[] sa = a.split("[.\\-+]");
        String[] sb = b.split("[.\\-+]");
        int n = Math.max(sa.length, sb.length);
        for (int i = 0; i < n; i++) {
            String x = i < sa.length ? sa[i] : "0";
            String y = i < sb.length ? sb[i] : "0";
            int cmp;
            if (isNumeric(x) && isNumeric(y)) {
                cmp = Long.compare(Long.parseLong(x), Long.parseLong(y));
            } else {
                cmp = x.compareTo(y);
            }
            if (cmp != 0) {
                return cmp;
            }
        }
        return 0;
    }

    private static boolean isNumeric(String v) {
        if (v == null || v.isEmpty()) {
            return false;
        }
        for (int i = 0; i < v.length(); i++) {
            if (!Character.isDigit(v.charAt(i))) {
                return false;
            }
        }
        return true;
    }

    /** 对象相等判定（供上层去重）。 */
    public static boolean sameTenant(Long a, Long b) {
        return Objects.equals(nz(a), nz(b));
    }
}
