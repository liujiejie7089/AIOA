package cn.aios.org.service;

import cn.aios.common.exception.BizException;
import cn.aios.org.entity.AttendanceRecord;
import cn.aios.org.entity.LocationConsent;
import cn.aios.org.mapper.AttendanceRecordMapper;
import cn.aios.org.mapper.LocationConsentMapper;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.security.SecureRandom;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 定位授权 + 考勤打卡（2026-11-05，docs/74）。
 *
 * <p><b>为什么把「同意」做成服务端凭据而不是前端弹窗</b>：能凭坐标换出考勤记录的接口，
 * 必须能证明「这一次是他本人同意的」。所以流程被拆成两段，中间隔着一张授权单：</p>
 * <pre>
 *   ① 申请：{@link #requestConsent} —— 只建一张 PENDING 单，不碰任何坐标；
 *   ② 同意：用户在卡片上点「允许」后，前端把浏览器取到的坐标连同 token 一起提交给
 *      {@link #clock}，服务端据 token 把单子置 GRANTED 并**在同一次事务里**落考勤记录。
 * </pre>
 * <p>换句话说：<b>没有申请单就调不动打卡接口</b>，而申请单只能用一次、只用 5 分钟、
 * 只属于申请它的人。改前端 JS 或直接 curl 都绕不过这一条。</p>
 *
 * <p><b>为什么坐标不直接信任</b>：浏览器可以伪造经纬度，这是 Web 的固有限制，本服务不假装能防。
 * 能防的是「有没有同意」「是不是本人」「是不是这一次」；伪造坐标留给管理端事后核对
 * （每条记录都存了精度与来源，异常值可查），而不是在这里做一个看似严格实则无效的距离校验。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AttendanceService {

    /** 授权单有效期：够用户看清文案并点一下，又不会长到能被人捡走重放。 */
    private static final int CONSENT_TTL_MINUTES = 5;

    /** 待处理列表最多回 1 条 —— 语义是「现在要不要弹卡」，不是翻历史。 */
    private static final DateTimeFormatter HM = DateTimeFormatter.ofPattern("HH:mm");

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final char[] TOKEN_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789".toCharArray();

    private final LocationConsentMapper consentMapper;
    private final AttendanceRecordMapper recordMapper;

    // ------------------------------------------------------------------ 申请

    /**
     * 创建一张定位申请（不取坐标、不做任何定位动作）。
     *
     * @param origin H5（用户点「打卡」入口）或 AI（数字人调用工具）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> requestConsent(AuthUser user, String origin, String purpose) {
        expireStale(user);
        LocalDateTime now = LocalDateTime.now();
        LocationConsent c = new LocationConsent();
        c.setTenantId(tenantOf(user));
        c.setUserId(user.getUserId());
        c.setToken(newToken());
        c.setPurpose(purpose == null || purpose.isBlank() ? LocationConsent.PURPOSE_ATTENDANCE : purpose);
        c.setOrigin("AI".equalsIgnoreCase(origin) ? "AI" : "H5");
        c.setStatus(LocationConsent.STATUS_PENDING);
        c.setPrompt(promptText(user, c.getOrigin()));
        c.setExpiresAt(now.plusMinutes(CONSENT_TTL_MINUTES));
        c.setCreatedAt(now);
        c.setCreatedBy(user.getUserId());
        consentMapper.insert(c);
        log.info("location consent requested: id={} user={} origin={}", c.getId(), user.getUserId(), c.getOrigin());
        return consentView(c, now);
    }

    /** 当前待处理的申请（超过有效期的不返回，并顺手标记 EXPIRED）。 */
    public Map<String, Object> pending(AuthUser user) {
        expireStale(user);
        LocalDateTime now = LocalDateTime.now();
        List<LocationConsent> rows = consentMapper.selectList(Wrappers.<LocationConsent>lambdaQuery()
                .eq(LocationConsent::getTenantId, tenantOf(user))
                .eq(LocationConsent::getUserId, user.getUserId())
                .eq(LocationConsent::getStatus, LocationConsent.STATUS_PENDING)
                .gt(LocationConsent::getExpiresAt, now)
                .orderByDesc(LocationConsent::getId)
                .last("LIMIT 1"));
        return rows.isEmpty() ? null : consentView(rows.get(0), now);
    }

    /** 用户点了「不允许」：留痕（拒绝率是判断「申请时机是否打扰」的唯一依据）。 */
    @Transactional(rollbackFor = Exception.class)
    public void deny(AuthUser user, Long id) {
        LocationConsent c = requireOwn(user, id);
        if (!LocationConsent.STATUS_PENDING.equals(c.getStatus())) {
            // 已经被用过/已拒绝：重复点击不再报错（前端可能因网络重试），但也不改状态
            log.info("deny ignored: consent {} status={}", id, c.getStatus());
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        c.setStatus(LocationConsent.STATUS_DENIED);
        c.setDeniedAt(now);
        c.setUpdatedAt(now);
        c.setUpdatedBy(user.getUserId());
        consentMapper.updateById(c);
    }

    // ------------------------------------------------------------------ 打卡

    /**
     * 打卡（**唯一入口**，H5 与数字人共用）。
     *
     * <p>三种失败都回 200 + code=400（表单/业务校验口径，见铁律 29），前端按可读文案提示：
     * 没有授权单、授权单不属于本人、授权单过期/已用。</p>
     *
     * @param body {token, latitude, longitude, accuracy?, clockType?, placeName?, source?}
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> clock(AuthUser user, Map<String, Object> body) {
        String token = str(body.get("token"));
        if (token.isBlank()) {
            throw BizException.badRequest("打卡需要一次定位授权：请先同意定位申请，再点一次打卡");
        }
        LocalDateTime now = LocalDateTime.now();
        LocationConsent c = consentMapper.selectOne(Wrappers.<LocationConsent>lambdaQuery()
                .eq(LocationConsent::getToken, token)
                .eq(LocationConsent::getTenantId, tenantOf(user))
                .last("LIMIT 1"));
        if (c == null) {
            throw BizException.badRequest("定位授权已失效，请重新发起打卡");
        }
        if (!user.getUserId().equals(c.getUserId())) {
            // 别人的授权单：这不是业务校验，是越权，按 403 处理
            throw BizException.forbidden("这张定位授权不是你的，无法用于打卡");
        }
        if (LocationConsent.STATUS_EXPIRED.equals(c.getStatus())
                || (c.getExpiresAt() != null && !c.getExpiresAt().isAfter(now))) {
            throw BizException.badRequest("定位授权已超过 " + CONSENT_TTL_MINUTES + " 分钟有效期，请重新点击打卡");
        }
        if (LocationConsent.STATUS_USED.equals(c.getStatus())) {
            throw BizException.badRequest("这张定位授权已经用过了，请重新点击打卡");
        }
        if (LocationConsent.STATUS_DENIED.equals(c.getStatus())) {
            throw BizException.badRequest("你刚才拒绝了定位申请，无法打卡；需要打卡请重新同意");
        }

        BigDecimal lat = dec(body.get("latitude"), "纬度", -90, 90);
        BigDecimal lng = dec(body.get("longitude"), "经度", -180, 180);
        if (lat == null || lng == null) {
            throw BizException.badRequest("没有拿到定位坐标，无法打卡");
        }

        // 同意与打卡在同一次事务里完成：用户点「允许」的那一刻就是授权生效的时刻。
        c.setStatus(LocationConsent.STATUS_GRANTED);
        c.setLatitude(lat);
        c.setLongitude(lng);
        c.setAccuracyM(dec(body.get("accuracy"), "定位精度", 0, 100000));
        c.setGrantedAt(now);
        c.setConsentText(str(body.get("consentText")));
        c.setUpdatedAt(now);
        c.setUpdatedBy(user.getUserId());
        consentMapper.updateById(c);

        LocalDate day = now.toLocalDate();
        String type = clockType(body.get("clockType"), user, day);
        AttendanceRecord exist = recordMapper.selectOne(Wrappers.<AttendanceRecord>lambdaQuery()
                .eq(AttendanceRecord::getTenantId, tenantOf(user))
                .eq(AttendanceRecord::getUserId, user.getUserId())
                .eq(AttendanceRecord::getWorkDate, day)
                .eq(AttendanceRecord::getClockType, type)
                .last("LIMIT 1"));
        if (exist != null) {
            // 幂等：同一类型一天只留一条。授权单仍置 USED，避免同一张单再被拿去刷别的类型。
            consume(c, now, user);
            Map<String, Object> out = recordView(exist);
            out.put("duplicated", true);
            out.put("message", "今天" + typeLabel(type) + "已经打过卡了（" + exist.getClockedAt().format(HM) + "），未重复记录");
            return out;
        }

        AttendanceRecord r = new AttendanceRecord();
        r.setTenantId(tenantOf(user));
        r.setUserId(user.getUserId());
        r.setWorkDate(day);
        r.setClockType(type);
        r.setClockedAt(now);
        r.setLatitude(lat);
        r.setLongitude(lng);
        r.setAccuracyM(c.getAccuracyM());
        r.setPlaceName(str(body.get("placeName")));
        r.setSource(normalizeSource(body.get("source")));
        r.setConsentId(c.getId());
        r.setRemark(str(body.get("remark")));
        r.setCreatedAt(now);
        r.setCreatedBy(user.getUserId());
        recordMapper.insert(r);
        consume(c, now, user);

        log.info("attendance clocked: user={} date={} type={} source={} consent={}",
                user.getUserId(), day, type, r.getSource(), c.getId());
        Map<String, Object> out = recordView(r);
        out.put("duplicated", false);
        out.put("message", "打卡成功：" + typeLabel(type) + " " + now.format(HM));
        return out;
    }

    /** 今日考勤快照（数字人回答「我今天打卡了吗」的唯一数据源）。 */
    public Map<String, Object> today(AuthUser user) {
        LocalDate day = LocalDate.now();
        List<AttendanceRecord> rows = recordMapper.selectList(Wrappers.<AttendanceRecord>lambdaQuery()
                .eq(AttendanceRecord::getTenantId, tenantOf(user))
                .eq(AttendanceRecord::getUserId, user.getUserId())
                .eq(AttendanceRecord::getWorkDate, day)
                .orderByAsc(AttendanceRecord::getClockedAt));
        List<Map<String, Object>> records = new ArrayList<>();
        for (AttendanceRecord r : rows) {
            records.add(recordView(r));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("date", day.toString());
        out.put("records", records);
        out.put("clockedOn", rows.stream().anyMatch(r -> AttendanceRecord.TYPE_ON.equals(r.getClockType())));
        out.put("clockedOff", rows.stream().anyMatch(r -> AttendanceRecord.TYPE_OFF.equals(r.getClockType())));
        out.put("pendingConsent", pending(user));
        return out;
    }

    /** 近 N 天考勤（N 上限 31，避免模型一次拉出全量历史）。 */
    public Map<String, Object> recent(AuthUser user, int days) {
        int n = Math.max(1, Math.min(days, 31));
        LocalDate from = LocalDate.now().minusDays(n - 1L);
        List<AttendanceRecord> rows = recordMapper.selectList(Wrappers.<AttendanceRecord>lambdaQuery()
                .eq(AttendanceRecord::getTenantId, tenantOf(user))
                .eq(AttendanceRecord::getUserId, user.getUserId())
                .ge(AttendanceRecord::getWorkDate, from)
                .orderByDesc(AttendanceRecord::getWorkDate)
                .orderByAsc(AttendanceRecord::getClockedAt));
        List<Map<String, Object>> records = new ArrayList<>();
        for (AttendanceRecord r : rows) {
            records.add(recordView(r));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("from", from.toString());
        out.put("to", LocalDate.now().toString());
        out.put("records", records);
        out.put("count", records.size());
        return out;
    }

    // ------------------------------------------------------------------ 内部

    private void consume(LocationConsent c, LocalDateTime now, AuthUser user) {
        c.setStatus(LocationConsent.STATUS_USED);
        c.setUsedAt(now);
        c.setUpdatedAt(now);
        c.setUpdatedBy(user.getUserId());
        consentMapper.updateById(c);
    }

    /** 惰性过期：没有定时任务，任何一次读/写都顺手把过期单置 EXPIRED（幂等）。 */
    private void expireStale(AuthUser user) {
        LocalDateTime now = LocalDateTime.now();
        List<LocationConsent> stale = consentMapper.selectList(Wrappers.<LocationConsent>lambdaQuery()
                .eq(LocationConsent::getTenantId, tenantOf(user))
                .eq(LocationConsent::getUserId, user.getUserId())
                .in(LocationConsent::getStatus,
                        LocationConsent.STATUS_PENDING, LocationConsent.STATUS_GRANTED)
                .le(LocationConsent::getExpiresAt, now));
        for (LocationConsent c : stale) {
            c.setStatus(LocationConsent.STATUS_EXPIRED);
            c.setUpdatedAt(now);
            consentMapper.updateById(c);
        }
    }

    private LocationConsent requireOwn(AuthUser user, Long id) {
        LocationConsent c = id == null ? null : consentMapper.selectById(id);
        if (c == null || !tenantOf(user).equals(c.getTenantId())) {
            throw BizException.notFound("定位申请不存在");
        }
        if (!user.getUserId().equals(c.getUserId())) {
            throw BizException.forbidden("这不是你的定位申请");
        }
        return c;
    }

    private String clockType(Object raw, AuthUser user, LocalDate day) {
        String v = str(raw).toUpperCase();
        if (AttendanceRecord.TYPE_ON.equals(v) || AttendanceRecord.TYPE_OFF.equals(v)) {
            return v;
        }
        // 未指定：今天还没上班卡就打上班，否则打下班 —— 比「必须让用户选」少一次交互，
        // 且结果可预期（前端卡片上会写清「本次记为下班卡」）。
        boolean hasOn = recordMapper.selectCount(Wrappers.<AttendanceRecord>lambdaQuery()
                .eq(AttendanceRecord::getTenantId, tenantOf(user))
                .eq(AttendanceRecord::getUserId, user.getUserId())
                .eq(AttendanceRecord::getWorkDate, day)
                .eq(AttendanceRecord::getClockType, AttendanceRecord.TYPE_ON)) > 0;
        return hasOn ? AttendanceRecord.TYPE_OFF : AttendanceRecord.TYPE_ON;
    }

    private static String normalizeSource(Object raw) {
        String v = str(raw).toUpperCase();
        if (AttendanceRecord.SOURCE_AI.equals(v) || AttendanceRecord.SOURCE_ADMIN.equals(v)) {
            return v;
        }
        return AttendanceRecord.SOURCE_H5;
    }

    private static String typeLabel(String type) {
        return AttendanceRecord.TYPE_OFF.equals(type) ? "下班卡" : "上班卡";
    }

    private static String promptText(AuthUser user, String origin) {
        // 文案要说清「谁在问、问来做什么、多久、只这一次」四件事。昵称为空时用「你」，
        // 不要拼出「#3 手机的定位」这种内部 ID（用户看不懂，还会以为串号了）。
        String who = "AI".equals(origin) ? "数字人助手" : "本次打卡";
        String owner = (user.getNickname() == null || user.getNickname().isBlank()) ? "你" : user.getNickname();
        return who + "想使用一次" + owner + "手机的定位，仅用于记录这次打卡的位置，"
                + CONSENT_TTL_MINUTES + " 分钟内有效，且只用这一次。";
    }

    private static Map<String, Object> consentView(LocationConsent c, LocalDateTime now) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", c.getId());
        out.put("token", c.getToken());
        out.put("purpose", c.getPurpose());
        out.put("origin", c.getOrigin());
        out.put("prompt", c.getPrompt());
        out.put("status", c.getStatus());
        out.put("expiresAt", c.getExpiresAt() == null ? null : c.getExpiresAt().toString());
        out.put("expiresInSeconds", c.getExpiresAt() == null ? 0
                : Math.max(0, java.time.Duration.between(now, c.getExpiresAt()).getSeconds()));
        out.put("ttlMinutes", CONSENT_TTL_MINUTES);
        return out;
    }

    private static Map<String, Object> recordView(AttendanceRecord r) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", r.getId());
        out.put("date", r.getWorkDate() == null ? null : r.getWorkDate().toString());
        out.put("clockType", r.getClockType());
        out.put("clockTypeLabel", typeLabel(r.getClockType()));
        out.put("clockedAt", r.getClockedAt() == null ? null : r.getClockedAt().toString());
        out.put("time", r.getClockedAt() == null ? null : r.getClockedAt().format(HM));
        out.put("placeName", r.getPlaceName());
        out.put("source", r.getSource());
        // 坐标按 5 位小数回传（约 1 米精度），既不丢可用性也不把原始采样精度全量外抛
        out.put("latitude", r.getLatitude() == null ? null : r.getLatitude().setScale(5, java.math.RoundingMode.HALF_UP));
        out.put("longitude", r.getLongitude() == null ? null : r.getLongitude().setScale(5, java.math.RoundingMode.HALF_UP));
        out.put("accuracyM", r.getAccuracyM());
        return out;
    }

    private static BigDecimal dec(Object raw, String label, double lo, double hi) {
        if (raw == null || String.valueOf(raw).isBlank()) {
            return null;
        }
        try {
            BigDecimal v = new BigDecimal(String.valueOf(raw).trim());
            if (v.doubleValue() < lo || v.doubleValue() > hi) {
                throw BizException.badRequest(label + "超出合理范围（" + (long) lo + " ~ " + (long) hi + "）");
            }
            return v;
        } catch (NumberFormatException e) {
            throw BizException.badRequest(label + "格式不正确，无法识别");
        }
    }

    private static String str(Object raw) {
        return raw == null ? "" : String.valueOf(raw).trim();
    }

    private static Long tenantOf(AuthUser user) {
        return user.getTenantId() == null ? 0L : user.getTenantId();
    }

    private static String newToken() {
        StringBuilder sb = new StringBuilder(24);
        for (int i = 0; i < 24; i++) {
            sb.append(TOKEN_CHARS[RANDOM.nextInt(TOKEN_CHARS.length)]);
        }
        return sb.toString();
    }
}
