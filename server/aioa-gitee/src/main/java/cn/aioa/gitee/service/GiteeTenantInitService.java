package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.client.RepoProviderException;
import cn.aioa.gitee.client.RepoProviderClient;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteeTenantConfig;
import cn.aioa.gitee.mapper.GiteeTenantConfigMapper;
import cn.aioa.gitee.support.GiteeCrypto;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 企业主动发起 Gitee 初始化服务（组织级企业令牌）。
 *
 * <p><b>与 V50 的职责边界</b>：{@code GiteeTenantConfigService} 管辖 <b>org_name / enabled</b>
 * （组织归属与开关），本服务只管辖<b>企业令牌 + 初始化状态</b>。两者写不同列、互不越界，
 * 避免「初始化清掉了组织名」这类职责污染。</p>
 *
 * <p><b>为什么初始化必须硬校验（失败即中止）</b>：与 V50 保存时的 best-effort 探测不同，
 * 初始化是一次性的明确动作，静默成功比报错更有害——会让「组织其实不可用」的事实被埋掉。
 * 因此 7 步校验（GLOBAL_ENABLED → TENANT_ENABLED → TOKEN_FORMAT → ORG_FORMAT →
 * TOKEN_VALID → ORG_ACCESSIBLE → PERSIST）逐步记录，任一步硬失败即中止：</p>
 * <ul>
 *   <li>已有配置行：仅把该行 {@code init_status='FAILED'}、{@code last_error=原因}、
 *       {@code last_check_at=now}，<b>其余字段一字不改</b>（绝不覆盖 org_name/enabled/access_token）；</li>
 *   <li>从没有配置行：不落行，直接抛 {@link BizException#badRequest}。</li>
 * </ul>
 *
 * <p><b>令牌安全</b>：{@code access_token} 入库即 AES-GCM 加密（与 gitee_account 同规格）；
 * 任何视图都<b>不回传明文或令牌前缀</b>，status 仅回 {@code tokenConfigured}（布尔）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeTenantInitService {

    /** 合法访问令牌：字母/数字/-/_/.，长度 8–512（无空白）。 */
    private static final Pattern TOKEN_PATTERN = Pattern.compile("^[A-Za-z0-9._\\-]{8,512}$");

    /** 合法 Gitee org login：字母/数字/-/_/.，长度 1–128（与 V50 保持一致）。 */
    private static final Pattern ORG_PATTERN = Pattern.compile("^[A-Za-z0-9._-]{1,128}$");

    private final GiteeTenantConfigMapper mapper;
    private final RepoProviderClient client;
    private final GiteeCrypto crypto;
    private final RepoProviderSettings props;
    private final AuditRecorder auditRecorder;

    // ======================================================================
    // 对外接口
    // ======================================================================

    /** 初始化状态视图（不触发任何网络校验）。 */
    public Map<String, Object> status(AuthUser actor, Long tenantId) {
        return buildStatus(tenantId);
    }

    /**
     * 只校验不落库（跑到步骤 6 为止，永不写 last_error）。
     *
     * <p><b>与 initialize 的关键差异</b>：校验失败<b>不抛业务错误</b>，而是以
     * {@code code=0} 返回完整诊断报告 —— 顶层 {@code passed=false} + {@code failedStep}
     * + 全量 {@code steps}，让前端能逐步渲染「卡在哪一步」。若这里也按错误抛出，
     * 前端只能拿到一个字符串 message，{@code steps} 明细会随异常一起丢掉。</p>
     */
    public Map<String, Object> verify(AuthUser actor, Long tenantId, String accessToken, String orgName) {
        List<Map<String, Object>> steps = runChecks(tenantId, accessToken, orgName,
                null, null, null, false, actor);
        return withReport(buildStatus(tenantId), steps, true);
    }

    /** 校验并落库（含 PERSIST 步骤）。这是提交动作，任一步失败即抛业务错误中止。 */
    public Map<String, Object> initialize(AuthUser actor, Long tenantId, String accessToken, String orgName,
                                          Boolean enabled, String note, Boolean rotateToken) {
        List<Map<String, Object>> steps = runChecks(tenantId, accessToken, orgName,
                enabled, note, rotateToken, true, actor);
        return withReport(buildStatus(tenantId), steps, false);
    }

    /**
     * 组装诊断报告：顶层 {@code passed}（steps 全 ok）+ 首个失败步定位 + steps 明细。
     *
     * <p>{@code passed} 与 {@code steps} 同源推导，杜绝「顶层说通过、明细里有红字」的自相矛盾。</p>
     */
    private Map<String, Object> withReport(Map<String, Object> base,
                                           List<Map<String, Object>> steps, boolean verifyOnly) {
        Map<String, Object> failed = null;
        for (Map<String, Object> s : steps) {
            if (!Boolean.TRUE.equals(s.get("ok"))) {
                failed = s;
                break;
            }
        }
        base.put("steps", steps);
        base.put("verifyOnly", verifyOnly);
        base.put("passed", failed == null);
        base.put("failedStep", failed == null ? null : failed.get("code"));
        base.put("failedMessage", failed == null ? null : failed.get("message"));
        return base;
    }

    /**
     * 撤销企业令牌：清空 access_token/token_owner/token_scope/org_verified，
     * init_status 复位 PENDING，init_at/init_by/last_error 清空；<b>保留 org_name 与 enabled</b>。
     *
     * <p>无可撤销内容（无配置行或无令牌）时抛业务错误，不静默成功。</p>
     */
    public Map<String, Object> revoke(AuthUser actor, Long tenantId) {
        GiteeTenantConfig row = findRow(tenantId);
        if (row == null || !StringUtils.hasText(row.getAccessToken())) {
            throw BizException.badRequest("该企业尚未初始化 " + props.providerLabel() + " 令牌，无可撤销内容");
        }
        Map<String, Object> before = snapshot(row);
        mapper.update(null, new LambdaUpdateWrapper<GiteeTenantConfig>()
                .eq(GiteeTenantConfig::getId, row.getId())
                .set(GiteeTenantConfig::getAccessToken, null)
                .set(GiteeTenantConfig::getTokenOwner, null)
                .set(GiteeTenantConfig::getTokenScope, null)
                .set(GiteeTenantConfig::getOrgVerified, null)
                .set(GiteeTenantConfig::getInitStatus, "PENDING")
                .set(GiteeTenantConfig::getInitAt, null)
                .set(GiteeTenantConfig::getInitBy, null)
                .set(GiteeTenantConfig::getLastError, null));
        GiteeTenantConfig after = findRow(tenantId);
        auditRecorder.record(tenantId, 0L, actor, "GITEE_TENANT_INIT_REVOKE", "GITEE_TENANT_CONFIG",
                String.valueOf(tenantId), "撤销企业 " + props.providerLabel() + " 令牌（组织=" + str(row.getOrgName()) + "）",
                before, snapshot(after));
        Map<String, Object> m = buildStatus(tenantId);
        m.put("revoked", true);
        return m;
    }

    // ======================================================================
    // 状态视图
    // ======================================================================

    private Map<String, Object> buildStatus(Long tenantId) {
        GiteeTenantConfig row = findRow(tenantId);
        String defaultOrg = props.getOrg();
        // 与 GiteeTenantConfigService.tenantSuppliesOrg 同一判据，避免 source 自相矛盾
        boolean supplies = row != null
                && Boolean.TRUE.equals(row.getEnabled())
                && StringUtils.hasText(row.getOrgName());
        String effectiveOrg = supplies ? row.getOrgName() : defaultOrg;
        String source = supplies ? "TENANT" : "DEFAULT";
        boolean enabled = row == null || Boolean.TRUE.equals(row.getEnabled());

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("tenantId", tenantId);
        // 无配置行 / 空值统一读作 PENDING（= 未初始化）：契约不留 null，避免前端各自兜底。
        // 「是否真正落过行」由 configured / tokenConfigured 单独表达，语义不混。
        String initStatus = row == null ? null : row.getInitStatus();
        if (!StringUtils.hasText(initStatus)) {
            initStatus = "PENDING";
        }
        m.put("initialized", "ACTIVE".equals(initStatus));
        m.put("initStatus", initStatus);
        m.put("initAt", row == null ? null : row.getInitAt());
        m.put("initBy", row == null ? null : row.getInitBy());
        m.put("orgName", effectiveOrg);
        m.put("source", source);
        m.put("configured", row != null);
        m.put("enabled", enabled);
        m.put("tokenOwner", row == null ? null : row.getTokenOwner());
        m.put("tokenScope", row == null ? null : row.getTokenScope());
        m.put("orgVerified", row == null ? null : row.getOrgVerified());
        m.put("lastError", row == null ? null : row.getLastError());
        m.put("lastCheckAt", row == null ? null : row.getLastCheckAt());
        m.put("defaultOrg", defaultOrg);
        // 只表示有无令牌，绝不回传明文或令牌前缀
        m.put("tokenConfigured", row != null && StringUtils.hasText(row.getAccessToken()));
        return m;
    }

    // ======================================================================
    // 7 步校验（顺序执行，逐步记录，硬失败即中止）
    // ======================================================================

    private List<Map<String, Object>> runChecks(Long tenantId, String accessToken, String orgName,
                                                Boolean enabled, String note, Boolean rotateToken,
                                                boolean doPersist, AuthUser actor) {
        List<Map<String, Object>> steps = new ArrayList<>();
        GiteeTenantConfig existing = findRow(tenantId);
        String rawOrg = orgName == null ? "" : orgName.trim();

        // 1. GLOBAL_ENABLED
        if (!check(props.isEnabled(), steps, "GLOBAL_ENABLED", "平台能力开关",
                props.providerLabel() + " 能力已开启",
                props.providerLabel() + " 能力已在平台侧关闭（" + props.configKeyPrefix() + ".enabled=false），无法初始化",
                existing, doPersist)) {
            return steps;
        }

        // 2. TENANT_ENABLED
        boolean tenantDisabled = existing != null
                && !Boolean.TRUE.equals(existing.getEnabled())
                && !(enabled != null && enabled);
        if (!check(!tenantDisabled, steps, "TENANT_ENABLED", "租户联动开关",
                props.providerLabel() + " 仓库联动已启用",
                "本企业 " + props.providerLabel() + " 仓库联动已关闭，请先启用后再初始化",
                existing, doPersist)) {
            return steps;
        }

        // 令牌复用决策：rotateToken=false 且已有令牌且本次未传 accessToken → 复用已存令牌
        boolean rotate = Boolean.TRUE.equals(rotateToken);
        boolean hasStoredToken = existing != null && StringUtils.hasText(existing.getAccessToken());
        boolean reuseStored = !rotate && hasStoredToken && !StringUtils.hasText(accessToken);

        // 3. TOKEN_FORMAT
        if (reuseStored) {
            addStep(steps, "TOKEN_FORMAT", "访问令牌格式", true, "复用已存企业令牌，跳过格式校验");
        } else if (!StringUtils.hasText(accessToken)) {
            // 未传令牌、且无法沿用已存令牌（= 开启轮换，或本企业压根没配过令牌）。
            // 旧实现把 null 直接拼进用户可见文案（"…不合法：null"），既不可读也暴露内部值。
            // 这里显式区分两种成因，给出可操作的下一步。
            String blankMsg = hasStoredToken
                    ? "访问令牌不能为空：本次提交开启了令牌轮换却未填写新令牌；若要沿用已有企业令牌，请留空且不轮换后提交"
                    : "请填写访问令牌：本企业尚未配置企业令牌，首次初始化必须提供（留空仅适用于已配置令牌的企业）";
            if (!check(false, steps, "TOKEN_FORMAT", "访问令牌格式", null, blankMsg, existing, doPersist)) {
                return steps;
            }
        } else {
            boolean tokenFormatOk = TOKEN_PATTERN.matcher(accessToken).matches();
            if (!check(tokenFormatOk, steps, "TOKEN_FORMAT", "访问令牌格式",
                    "访问令牌格式合法",
                    "访问令牌格式不合法（长度需 8~512，仅允许字母/数字/._-）：" + accessToken,
                    existing, doPersist)) {
                return steps;
            }
        }

        // 4. ORG_FORMAT
        boolean orgFormatOk = ORG_PATTERN.matcher(rawOrg).matches();
        if (!check(orgFormatOk, steps, "ORG_FORMAT", "组织名格式",
                "组织名格式合法",
                props.providerLabel() + " 组织名非法（仅允许字母/数字/-/_/.，长度 1–128）：" + rawOrg,
                existing, doPersist)) {
            return steps;
        }

        // 实际用于后续调用的令牌
        String tokenForCalls;
        if (reuseStored) {
            try {
                tokenForCalls = crypto.decrypt(existing.getAccessToken());
            } catch (Exception e) {
                // 复用路径下无法解密 = 令牌不可用；走统一 check 收口（verify 返回报告、initialize 抛错）
                check(false, steps, "TOKEN_VALID", "访问令牌有效性",
                        null, "企业令牌无法解密，请重新初始化", existing, doPersist);
                return steps;
            }
        } else {
            tokenForCalls = accessToken;
        }

        // 5. TOKEN_VALID
        String tokenOwner;
        String tokenScope;
        if (reuseStored) {
            addStep(steps, "TOKEN_VALID", "访问令牌有效性", true, "复用已存企业令牌，跳过有效性校验");
            tokenOwner = existing.getTokenOwner();
            tokenScope = existing.getTokenScope();
        } else {
            boolean valid = false;
            String owner = null;
            String scope = null;
            String failMsg = "访问令牌校验失败";
            try {
                Map<String, Object> me = client.getUser(tokenForCalls);
                owner = str(me.get("login"));
                scope = str(me.get("scope"));
                if (StringUtils.hasText(owner)) {
                    valid = true;
                } else {
                    failMsg = "访问令牌有效但未返回账号信息";
                }
            } catch (RepoProviderException e) {
                if (e.getStatus() == 401 || e.getStatus() == 403) {
                    failMsg = "访问令牌无效或已过期（" + props.providerLabel() + " 返回 " + e.getStatus() + "）";
                } else {
                    failMsg = "访问令牌校验失败（" + props.providerLabel() + " 返回 " + e.getStatus() + "）：" + e.getMessage();
                }
            } catch (Exception e) {
                failMsg = "访问令牌校验失败：" + e.getMessage();
            }
            if (!check(valid, steps, "TOKEN_VALID", "访问令牌有效性",
                    "访问令牌有效，账号：" + owner,
                    failMsg,
                    existing, doPersist)) {
                return steps;
            }
            tokenOwner = owner;
            tokenScope = scope;
        }

        // 6. ORG_ACCESSIBLE
        boolean orgVerified = false;
        boolean accessible = false;
        String orgFailMsg = "组织校验失败";
        try {
            client.getOrg(tokenForCalls, rawOrg);
            accessible = true;
            orgVerified = true;
        } catch (RepoProviderException e) {
            if (e.getStatus() == 404) {
                orgFailMsg = "组织「" + rawOrg + "」不存在，或该令牌的账号不是该组织成员、无权访问";
            } else if (e.getStatus() == 403) {
                orgFailMsg = "令牌权限不足，无法读取组织信息";
            } else {
                orgFailMsg = "组织校验失败（" + props.providerLabel() + " 返回 " + e.getStatus() + "）：" + e.getMessage();
            }
        } catch (Exception e) {
            orgFailMsg = "组织校验失败：" + e.getMessage();
        }
        if (!check(accessible, steps, "ORG_ACCESSIBLE", "组织可访问性",
                "组织存在且令牌账号可访问",
                orgFailMsg,
                existing, doPersist)) {
            return steps;
        }

        // 7. PERSIST（仅 initialize 落库）
        if (doPersist) {
            persist(tenantId, rawOrg, enabled, note, reuseStored, existing,
                    tokenForCalls, tokenOwner, tokenScope, orgVerified, actor);
            addStep(steps, "PERSIST", "落库初始化", true, "企业 " + props.providerLabel() + " 初始化已完成");
        }
        return steps;
    }

    /**
     * 校验助手：ok → 记成功步并返回 {@code true}；否则记失败步 + 标 FAILED（仅 doPersist 且已有行），然后
     * <ul>
     *   <li>{@code doPersist=true}（initialize）：抛 {@link BizException#badRequest} 中止；</li>
     *   <li>{@code doPersist=false}（verify）：返回 {@code false}，由调用方收口为诊断报告，<b>不抛错</b>。</li>
     * </ul>
     * 调用方一律用 {@code if (!check(...)) return steps;} 收口，保证失败后不再执行后续步骤。
     */
    private boolean check(boolean ok, List<Map<String, Object>> steps, String code, String label,
                          String okMsg, String failMsg, GiteeTenantConfig existing, boolean doPersist) {
        if (ok) {
            addStep(steps, code, label, true, okMsg);
            return true;
        }
        addStep(steps, code, label, false, failMsg);
        markFailed(existing, failMsg, doPersist);
        if (doPersist) {
            throw BizException.badRequest(failMsg);
        }
        return false;
    }

    /** 已有配置行时仅把该行标 FAILED（其余字段一字不改）；无行或仅校验则不写。 */
    private void markFailed(GiteeTenantConfig existing, String msg, boolean doPersist) {
        if (existing == null || !doPersist) {
            return;
        }
        mapper.update(null, new LambdaUpdateWrapper<GiteeTenantConfig>()
                .eq(GiteeTenantConfig::getId, existing.getId())
                .set(GiteeTenantConfig::getInitStatus, "FAILED")
                .set(GiteeTenantConfig::getLastError, msg)
                .set(GiteeTenantConfig::getLastCheckAt, LocalDateTime.now()));
    }

    /** 落库（upsert 单行）。UPDATE 用 NOT_NULL 策略，未设置的列保持原值（职责分离：不碰 org_name/enabled 之外的无关列）。 */
    private void persist(Long tenantId, String orgName, Boolean enabled, String note,
                         boolean reuseStored, GiteeTenantConfig existing,
                         String tokenForCalls, String tokenOwner, String tokenScope,
                         boolean orgVerified, AuthUser actor) {
        LocalDateTime now = LocalDateTime.now();
        GiteeTenantConfig row = existing == null ? new GiteeTenantConfig() : existing;
        row.setTenantId(tenantId);
        row.setOrgName(orgName);
        row.setEnabled(enabled == null ? Boolean.TRUE : enabled);
        row.setNote(note);
        if (!reuseStored) {
            row.setAccessToken(crypto.encrypt(tokenForCalls));
            row.setTokenOwner(tokenOwner);
            row.setTokenScope(tokenScope);
        }
        row.setInitStatus("ACTIVE");
        row.setInitAt(now);
        row.setInitBy(actor.getUserId());
        row.setLastError(null);
        row.setOrgVerified(orgVerified);
        row.setLastCheckAt(now);

        Map<String, Object> before = existing == null ? null : snapshot(existing);
        if (existing == null) {
            row.setCreatedBy(actor.getUserId());
            mapper.insert(row);
        } else {
            mapper.updateById(row);
        }
        auditRecorder.record(tenantId, 0L, actor, "GITEE_TENANT_INIT", "GITEE_TENANT_CONFIG",
                String.valueOf(tenantId), "企业主动初始化 Gitee（组织=" + orgName + "）",
                before, snapshot(row));
    }

    // ======================================================================
    // 工具
    // ======================================================================

    private GiteeTenantConfig findRow(Long tenantId) {
        if (tenantId == null) {
            return null;
        }
        return mapper.selectOne(new LambdaQueryWrapper<GiteeTenantConfig>()
                .eq(GiteeTenantConfig::getTenantId, tenantId)
                .last("limit 1"));
    }

    private void addStep(List<Map<String, Object>> steps, String code, String label, boolean ok, String message) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("code", code);
        s.put("label", label);
        s.put("ok", ok);
        s.put("message", message);
        steps.add(s);
    }

    /** 审计快照：刻意排除 access_token（不含明文/密文/前缀）。 */
    private Map<String, Object> snapshot(GiteeTenantConfig r) {
        if (r == null) {
            return null;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("tenantId", r.getTenantId());
        m.put("orgName", r.getOrgName());
        m.put("enabled", r.getEnabled());
        m.put("initStatus", r.getInitStatus());
        m.put("tokenOwner", r.getTokenOwner());
        m.put("tokenScope", r.getTokenScope());
        m.put("orgVerified", r.getOrgVerified());
        m.put("note", r.getNote());
        return m;
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o).trim();
    }
}
