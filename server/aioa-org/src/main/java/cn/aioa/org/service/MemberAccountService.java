package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.entity.OrgMemberAccount;
import cn.aioa.org.mapper.OrgMemberAccountMapper;
import cn.aioa.org.support.AccountProvisioner;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 员工 ↔ 用户账号 的多对多维护（V67 / docs/38 批次 C）。
 *
 * <p>规格：「一个员工也可以有多个用户帐号」。此前只有 {@code org_member.user_id} 这一个单值外键，
 * 多账号无从表达。本服务是中间表 {@code org_member_account} 的**唯一写入口**。</p>
 *
 * <p><b>三条纪律</b>：</p>
 * <ol>
 *   <li><b>主账号与中间表同源</b>：{@code org_member.user_id} 仍是主账号（通知/审批/鉴权/机构归属都读它），
 *       中间表 {@code is_primary=1} 那一行由 {@link #syncPrimary} 同步维护 ——
 *       {@code is_primary=1} 只允许在这一处产生，别处不得直写。</li>
 *   <li><b>主账号不可解绑</b>：解绑主账号会让员工失去唯一身份口径（通知发给谁、归属哪个机构都会碎），
 *       因此只允许解绑附加账号，并给出明确文案 —— 不做静默降级。</li>
 *   <li><b>只能绑本租户的账号</b>：跨租户绑定是越权入口（把别的租户的账号挂到本租户员工上），
 *       故写入前校验账号的 {@code tenant_id} 必须与员工一致。</li>
 * </ol>
 *
 * <p>软删语义：解绑 = 软删（{@code @TableLogic}）。因唯一键含生成列 {@code alive}，
 * 解绑后重新绑定同一个账号**不会**撞唯一键，也**不需要复活旧行** —— 直接插新行即可
 * （这是刻意选择：复活软删行会被 MyBatis-Plus 的 {@code update} 自动附加的
 * {@code deleted_at IS NULL} 条件挡住，是很容易踩的坑）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MemberAccountService {

    /** 主账号标记。 */
    private static final int PRIMARY = 1;
    /** 附加账号标记。 */
    private static final int EXTRA = 0;

    private final OrgMemberAccountMapper accountMapper;
    private final cn.aioa.org.mapper.OrgStatMapper statMapper;
    private final AccountProvisioner accounts;
    private final AuditRecorder audit;

    // ================================================================== 查询

    /** 批量取「员工 id → 账号列表」（列表页用；一次 IN，避免 N+1）。 */
    public Map<Long, List<Map<String, Object>>> byMembers(Collection<Long> memberIds) {
        Map<Long, List<Map<String, Object>>> out = new LinkedHashMap<>();
        if (memberIds == null || memberIds.isEmpty()) {
            return out;
        }
        List<OrgMemberAccount> rows = accountMapper.selectList(new LambdaQueryWrapper<OrgMemberAccount>()
                .in(OrgMemberAccount::getMemberId, memberIds)
                .orderByDesc(OrgMemberAccount::getIsPrimary)
                .orderByAsc(OrgMemberAccount::getId));
        if (rows.isEmpty()) {
            return out;
        }
        List<Long> uids = rows.stream().map(OrgMemberAccount::getUserId).distinct().toList();
        Map<Long, Map<String, Object>> users = accounts.usersByIds(uids);
        for (OrgMemberAccount a : rows) {
            out.computeIfAbsent(a.getMemberId(), k -> new ArrayList<>())
                    .add(accountView(a, users.get(a.getUserId())));
        }
        return out;
    }

    /** 单个员工的账号列表。 */
    public List<Map<String, Object>> of(Long memberId) {
        if (memberId == null) {
            return List.of();
        }
        return byMembers(List.of(memberId)).getOrDefault(memberId, List.of());
    }

    /**
     * 给定一批账号，返回其中**没有任何员工绑定**的（即「虚拟账号」）。
     *
     * <p>规格里「有些管理员用户帐号是虚拟的，没有对应的员工」。判据就是本表查不到行 ——
     * 不新增 {@code is_virtual} 列（docs/38 §3 假设 6），避免出现"两处判定谁是虚拟账号"。</p>
     */
    public Set<Long> virtualUserIds(Collection<Long> userIds) {
        Set<Long> all = new HashSet<>(userIds == null ? List.of() : userIds);
        if (all.isEmpty()) {
            return all;
        }
        List<OrgMemberAccount> rows = accountMapper.selectList(new LambdaQueryWrapper<OrgMemberAccount>()
                .in(OrgMemberAccount::getUserId, all));
        for (OrgMemberAccount a : rows) {
            all.remove(a.getUserId());
        }
        return all;
    }

    /**
     * 本租户的账号清单（「给员工绑定账号」的候选；同时显式标注**虚拟账号**）。
     *
     * <p>{@code virtual=true} 的账号没有被任何员工绑定 —— 即规格里的「虚拟管理员账号」。
     * 判据来自中间表，而不是新加一个列（避免"谁算虚拟账号"出现两处判定）。</p>
     */
    public List<Map<String, Object>> candidates(Long tenantId, String keyword) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> u : statMapper.selectTenantAccounts(tenantId, keyword)) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("userId", u.get("id"));
            m.put("username", u.get("username"));
            m.put("nickname", u.get("nickname"));
            m.put("status", u.get("status"));
            m.put("boundMemberName", u.get("boundMemberName"));
            m.put("virtual", u.get("boundMemberName") == null);
            out.add(m);
        }
        return out;
    }

    // ================================================================== 写

    /**
     * 同步主账号行 —— {@code is_primary=1} 的**唯一**产生处。
     *
     * <p>在员工开户（新建/批量导入）后调用。做两件事：把该员工的其它主标记降级、把目标账号置为主。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public void syncPrimary(OrgMember member, Long actorId) {
        if (member == null || member.getId() == null || member.getUserId() == null) {
            return;
        }
        Long memberId = member.getId();
        Long uid = member.getUserId();
        for (OrgMemberAccount a : aliveRows(memberId)) {
            if (a.getIsPrimary() != null && a.getIsPrimary() == PRIMARY && !uid.equals(a.getUserId())) {
                a.setIsPrimary(EXTRA);
                a.setUpdatedAt(LocalDateTime.now());
                accountMapper.updateById(a);
            }
        }
        OrgMemberAccount exists = aliveRow(memberId, uid);
        if (exists != null) {
            if (exists.getIsPrimary() == null || exists.getIsPrimary() != PRIMARY) {
                exists.setIsPrimary(PRIMARY);
                exists.setUpdatedAt(LocalDateTime.now());
                accountMapper.updateById(exists);
            }
            return;
        }
        insert(memberId, member.getTenantId(), uid, PRIMARY, actorId);
    }

    /** 追加绑定一个账号（不改变主账号）。 */
    @Transactional(rollbackFor = Exception.class)
    public List<Map<String, Object>> attach(OrgMember member, AuthUser actor, Long userId) {
        if (userId == null) {
            throw BizException.badRequest("请选择要绑定的账号");
        }
        if (userId.equals(member.getUserId())) {
            throw BizException.badRequest("该账号已是此员工的主账号，无需重复绑定");
        }
        Map<String, Object> u = accounts.usersByIds(List.of(userId)).get(userId);
        if (u == null) {
            throw BizException.notFound("账号不存在：" + userId);
        }
        Long ut = longOf(u.get("tenantId"));
        if (ut == null || !ut.equals(member.getTenantId() == null ? 0L : member.getTenantId())) {
            throw BizException.forbidden("不能绑定其它租户的账号：" + u.get("username"));
        }
        if (aliveRow(member.getId(), userId) != null) {
            throw BizException.badRequest("该账号已绑定此员工：" + u.get("username"));
        }
        insert(member.getId(), member.getTenantId(), userId, EXTRA, actor.getUserId());
        List<Map<String, Object>> after = of(member.getId());
        audit.record(member.getTenantId(), member.getInstitutionId(), actor,
                "MEMBER_ACCOUNT_ATTACH", "ORG_MEMBER", member.getId(),
                "给员工「" + member.getName() + "」追加账号 " + u.get("username"), null, after);
        return after;
    }

    /** 解绑一个**附加**账号（主账号不可解绑）。 */
    @Transactional(rollbackFor = Exception.class)
    public List<Map<String, Object>> detach(OrgMember member, AuthUser actor, Long userId) {
        if (userId == null) {
            throw BizException.badRequest("请指定要解绑的账号");
        }
        if (userId.equals(member.getUserId())) {
            throw BizException.badRequest("主账号不可解绑：员工必须保留一个主账号，"
                    + "如需更换请先在员工资料里改主账号");
        }
        List<Map<String, Object>> before = of(member.getId());
        OrgMemberAccount row = aliveRow(member.getId(), userId);
        if (row == null) {
            throw BizException.notFound("该账号未绑定此员工：" + userId);
        }
        accountMapper.deleteById(row.getId());
        List<Map<String, Object>> after = of(member.getId());
        audit.record(member.getTenantId(), member.getInstitutionId(), actor,
                "MEMBER_ACCOUNT_DETACH", "ORG_MEMBER", member.getId(),
                "解绑员工「" + member.getName() + "」的账号 #" + userId, before, after);
        return after;
    }

    /** 员工被移除时清掉它的全部账号绑定（避免中间表留下指向已删员工的孤儿行）。 */
    @Transactional(rollbackFor = Exception.class)
    public void dropAll(Long memberId) {
        if (memberId == null) {
            return;
        }
        for (OrgMemberAccount a : aliveRows(memberId)) {
            accountMapper.deleteById(a.getId());
        }
    }

    // ================================================================== 内部

    private void insert(Long memberId, Long tenantId, Long userId, int primary, Long actorId) {
        OrgMemberAccount a = new OrgMemberAccount();
        a.setTenantId(tenantId == null ? 0L : tenantId);
        a.setMemberId(memberId);
        a.setUserId(userId);
        a.setIsPrimary(primary);
        a.setCreatedAt(LocalDateTime.now());
        a.setCreatedBy(actorId);
        accountMapper.insert(a);
    }

    private List<OrgMemberAccount> aliveRows(Long memberId) {
        return accountMapper.selectList(new LambdaQueryWrapper<OrgMemberAccount>()
                .eq(OrgMemberAccount::getMemberId, memberId)
                .orderByAsc(OrgMemberAccount::getId));
    }

    private OrgMemberAccount aliveRow(Long memberId, Long userId) {
        if (memberId == null || userId == null) {
            return null;
        }
        return accountMapper.selectOne(new LambdaQueryWrapper<OrgMemberAccount>()
                .eq(OrgMemberAccount::getMemberId, memberId)
                .eq(OrgMemberAccount::getUserId, userId)
                .orderByAsc(OrgMemberAccount::getId)
                .last("limit 1"));
    }

    private Map<String, Object> accountView(OrgMemberAccount a, Map<String, Object> user) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("userId", a.getUserId());
        m.put("username", user == null ? null : user.get("username"));
        m.put("nickname", user == null ? null : user.get("nickname"));
        m.put("status", user == null ? null : user.get("status"));
        m.put("isPrimary", a.getIsPrimary() != null && a.getIsPrimary() == PRIMARY);
        return m;
    }

    private static Long longOf(Object v) {
        if (v instanceof Number n) {
            return n.longValue();
        }
        if (v == null) {
            return null;
        }
        try {
            return Long.valueOf(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
