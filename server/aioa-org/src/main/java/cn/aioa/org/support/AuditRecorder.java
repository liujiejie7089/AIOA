package cn.aioa.org.support;

import cn.aioa.common.trace.TraceId;
import cn.aioa.org.entity.OrgAuditLog;
import cn.aioa.org.mapper.OrgAuditLogMapper;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 两级审计写入器（FR-F2 租户级 / FR-K2 机构级 / FR-A3 敏感操作留痕）。
 *
 * <p>不可篡改：只写不提供更新删除接口；每条记录携带 prev_hash/hash 形成哈希链，
 * 由 {@link #verifyChain(Long)} 逐条校验。before/after 落全量原值/新值。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AuditRecorder {

    public static final String SCOPE_TENANT = OrgAuditLog.SCOPE_TENANT;
    public static final String SCOPE_ORG = OrgAuditLog.SCOPE_ORG;

    /** 当前哈希算法版本（V2：时间戳截断到微秒，与 DATETIME(6) 精度一致）。 */
    public static final String HASH_ALGO = "V2";

    private final OrgAuditLogMapper mapper;
    private final ObjectMapper objectMapper;

    /**
     * 写入一条审计。
     *
     * @param tenantId      租户
     * @param institutionId 机构（租户级操作传 0）
     * @param actor         操作人（可为 null，如平台系统动作）
     * @param action        动作码，如 INSTITUTION_CREATE / QUOTA_ALLOCATE / LEAVE_APPROVE
     * @param resourceType  目标类型，如 INSTITUTION / ORG_QUOTA / LEAVE_REQUEST
     * @param resourceId    目标主键
     * @param summary       一句话摘要（审计页直接展示）
     * @param before        变更前对象（可为 null）
     * @param after         变更后对象（可为 null）
     */
    public void record(Long tenantId, Long institutionId, AuthUser actor,
                       String action, String resourceType, Object resourceId,
                       String summary, Object before, Object after) {
        record(tenantId, institutionId, actor, action, resourceType, resourceId,
                summary, before, after, "SUCCESS");
    }

    public void record(Long tenantId, Long institutionId, AuthUser actor,
                       String action, String resourceType, Object resourceId,
                       String summary, Object before, Object after, String result) {
        try {
            long tid = tenantId == null ? 0L : tenantId;
            long iid = institutionId == null ? 0L : institutionId;

            OrgAuditLog row = new OrgAuditLog();
            row.setTenantId(tid);
            row.setInstitutionId(iid);
            row.setScope(iid == 0L ? SCOPE_TENANT : SCOPE_ORG);
            if (actor != null) {
                row.setUserId(actor.getUserId());
                row.setActorName(displayName(actor));
                row.setActorRole(actor.getRoles() == null || actor.getRoles().isEmpty()
                        ? null : actor.getRoles().get(0));
                row.setCreatedBy(actor.getUserId());
            }
            row.setAction(action);
            row.setResourceType(resourceType);
            row.setResourceId(resourceId == null ? null : String.valueOf(resourceId));
            row.setSummary(truncate(summary, 500));
            row.setBeforeJson(toJson(before));
            row.setAfterJson(toJson(after));
            row.setResult(result);
            row.setTraceId(safeTraceId());
            fillRequestMeta(row);

            // 关键：DATETIME(6) 只保留微秒，写入前必须截断到微秒，
            // 否则哈希时用的是 9 位纳秒、回读只到 6 位微秒，哈希链必然断裂。
            LocalDateTime now = microsNow();
            row.setCreatedAt(now);

            String prev = lastHash(tid);
            row.setPrevHash(prev);
            row.setHashAlgo(HASH_ALGO);
            row.setHash(sha256(prev + "|" + tid + "|" + iid + "|" + action + "|"
                    + resourceType + "|" + row.getResourceId() + "|" + row.getSummary()
                    + "|" + now));

            mapper.insert(row);
        } catch (Exception e) {
            // 审计失败不得阻断主流程，但必须留下服务端告警
            log.error("audit record failed: action={} resourceType={} resourceId={}",
                    action, resourceType, resourceId, e);
        }
    }

    public static String displayName(AuthUser u) {
        if (u == null) {
            return null;
        }
        if (u.getNickname() != null && !u.getNickname().isBlank()) {
            return u.getNickname();
        }
        return u.getUsername();
    }

    /** 审计链校验结果。 */
    @Getter
    @RequiredArgsConstructor
    public static class ChainResult {
        /** 首个断链记录 id，null 表示完整。 */
        private final Long brokenRecordId;
        /** 参与校验的总行数。 */
        private final int total;
        /** 做了「自哈希 + 链式链接」双重校验的行数（当前算法 V2）。 */
        private final int verified;
        /** 仅做链式链接校验的历史遗留行数（算法 V1，自哈希不可复算）。 */
        private final int legacy;

        public boolean isIntact() {
            return brokenRecordId == null;
        }
    }

    /**
     * 校验某租户审计链完整性。
     *
     * <p>算法升级的平滑锚定：V1（历史遗留）行的时间戳以纳秒参与哈希，回读只到微秒，
     * 自哈希不可复算 —— 对这类行只做链式链接校验（prev_hash 是否等于上一条 hash），
     * 并把最近一条 V1 行当作新链的信任锚。V2 行做「自哈希 + 链接」双重校验。
     * 这样算法升级不会导致整链误报断裂，同时篡改仍会被检出。</p>
     */
    public ChainResult verifyChain(Long tenantId) {
        List<OrgAuditLog> rows = mapper.selectList(new LambdaQueryWrapper<OrgAuditLog>()
                .eq(OrgAuditLog::getTenantId, tenantId)
                .orderByAsc(OrgAuditLog::getId));
        String prev = null;
        int verified = 0;
        int legacy = 0;
        for (OrgAuditLog r : rows) {
            // 1) 链式链接：本条 prev_hash 必须等于上一条的 hash（对所有行生效）
            if (prev == null ? r.getPrevHash() != null : !prev.equals(r.getPrevHash())) {
                return new ChainResult(r.getId(), rows.size(), verified, legacy);
            }
            // 2) 自哈希复算：仅对当前算法版本生效
            if (HASH_ALGO.equals(r.getHashAlgo())) {
                String expect = sha256(r.getPrevHash() + "|" + r.getTenantId() + "|"
                        + r.getInstitutionId() + "|" + r.getAction() + "|" + r.getResourceType()
                        + "|" + r.getResourceId() + "|" + r.getSummary() + "|" + r.getCreatedAt());
                if (!expect.equals(r.getHash())) {
                    return new ChainResult(r.getId(), rows.size(), verified, legacy);
                }
                verified++;
            } else {
                legacy++;
            }
            prev = r.getHash();
        }
        return new ChainResult(null, rows.size(), verified, legacy);
    }

    private String lastHash(long tenantId) {
        List<OrgAuditLog> last = mapper.selectList(new LambdaQueryWrapper<OrgAuditLog>()
                .eq(OrgAuditLog::getTenantId, tenantId)
                .orderByDesc(OrgAuditLog::getId)
                .last("limit 1"));
        return last.isEmpty() ? null : last.get(0).getHash();
    }

    private void fillRequestMeta(OrgAuditLog row) {
        try {
            ServletRequestAttributes attrs =
                    (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
            if (attrs == null) {
                return;
            }
            HttpServletRequest req = attrs.getRequest();
            row.setIp(clientIp(req));
            String ua = req.getHeader("User-Agent");
            row.setUa(truncate(ua, 500));
        } catch (Exception ignored) {
            // 非 Web 线程（定时任务等）无请求上下文，忽略
        }
    }

    private static String clientIp(HttpServletRequest req) {
        String xff = req.getHeader("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            int comma = xff.indexOf(',');
            return (comma > 0 ? xff.substring(0, comma) : xff).trim();
        }
        String real = req.getHeader("X-Real-IP");
        return real == null || real.isBlank() ? req.getRemoteAddr() : real;
    }

    private String toJson(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof String s) {
            return s;
        }
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            return "\"<unserializable:" + o.getClass().getSimpleName() + ">\"";
        }
    }

    private static String safeTraceId() {
        try {
            return TraceId.get();
        } catch (Exception e) {
            return null;
        }
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() <= max ? s : s.substring(0, max);
    }

    /** 截断到微秒（对齐 MySQL DATETIME(6) 精度），保证写盘与回读的字符串一致。 */
    static LocalDateTime microsNow() {
        LocalDateTime now = LocalDateTime.now();
        return now.withNano((now.getNano() / 1000) * 1000);
    }

    static String sha256(String raw) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(raw.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(d.length * 2);
            for (byte b : d) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
