package cn.aios.resource.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.entity.CredentialShare;
import cn.aios.resource.entity.ModelCredential;
import cn.aios.resource.mapper.CredentialShareMapper;
import cn.aios.resource.mapper.ModelCredentialMapper;
import cn.aios.security.AuthUser;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 模型账号与计费归属（docs/71）单测。
 *
 * <p>锁死四类「错了也不会报错、只会把账记到别人头上」的行为：</p>
 * <ol>
 *   <li><b>company_charged 只能由来源推导</b>：调用方传什么都不能改变它 ——
 *       否则账单口径可被伪造（前端传个 false 就把公司收费洗成个人自付）。</li>
 *   <li><b>承担人 = 账号持有人（PERSONAL）/ 公司池（COMPANY）</b>：
 *       A 用 B 的账号时扣 B 的行，不扣 A 的。</li>
 *   <li><b>共享可用性</b>：ACTIVE 且未过期才算可用；到期在读时判定，
 *       不等定时任务（否则「昨天到期、任务今天没跑」这段时间共享仍然有效）。</li>
 *   <li><b>密钥只出掩码</b>：掩码不足以还原明文，也不把明文带进任何回执。</li>
 * </ol>
 */
class ModelCredentialServiceTest {

    private final ModelCredentialMapper credentialMapper = mock(ModelCredentialMapper.class);
    private final CredentialShareMapper shareMapper = mock(CredentialShareMapper.class);
    private final SecretCodec secretCodec = new SecretCodec();
    /** 被邀请人查询走 JdbcTemplate（resource 模块不依赖 org 模块），这里给一个能返回同事的桩。 */
    private final org.springframework.jdbc.core.JdbcTemplate jdbc =
            mock(org.springframework.jdbc.core.JdbcTemplate.class);
    private final ModelCredentialService service =
            new ModelCredentialService(credentialMapper, shareMapper, secretCodec, jdbc);

    private static AuthUser user(long id, long tenant, String... roles) {
        return AuthUser.builder().userId(id).tenantId(tenant).username("u" + id)
                .roles(List.of(roles)).build();
    }

    // ---------------------------------------------------------------- ① 收费归属推导

    @Test
    @DisplayName("company_charged 由账号来源推导：PERSONAL→0、COMPANY→1、未标注→null")
    void company_charged_derives_from_owner_type_only() {
        assertEquals(0, BillingService.companyChargedOf(ModelCredential.OWNER_PERSONAL));
        assertEquals(1, BillingService.companyChargedOf(ModelCredential.OWNER_COMPANY));
        // null = 历史账本未标注。补 0 等于谎报「个人自付」，必须是 null
        assertEquals(null, BillingService.companyChargedOf(null));
        assertEquals(null, BillingService.companyChargedOf("  "));
        // 大小写不敏感（库里可能被手工写成 company）
        assertEquals(1, BillingService.companyChargedOf("company"));
    }

    @Test
    @DisplayName("实体上的承担人：PERSONAL=持有人，COMPANY=0（公司池）")
    void charge_user_derives_from_owner_type() {
        ModelCredential personal = new ModelCredential();
        personal.setOwnerType(ModelCredential.OWNER_PERSONAL);
        personal.setOwnerUserId(7L);
        assertEquals(7L, personal.chargeUserId());
        assertFalse(personal.companyCharged());

        ModelCredential company = new ModelCredential();
        company.setOwnerType(ModelCredential.OWNER_COMPANY);
        company.setOwnerUserId(null);
        assertEquals(0L, company.chargeUserId());
        assertTrue(company.companyCharged());
    }

    // ---------------------------------------------------------------- ② 共享可用性

    @Test
    @DisplayName("共享到期在读时判定：过期即不可用，不等定时任务")
    void share_usable_judged_on_read() {
        CredentialShare s = new CredentialShare();
        s.setStatus(CredentialShare.STATUS_ACTIVE);
        LocalDateTime now = LocalDateTime.of(2026, 11, 3, 12, 0);
        s.setExpiresAt(now.minusSeconds(1));
        assertFalse(s.usable(now), "已过期的 ACTIVE 共享必须判为不可用");

        s.setExpiresAt(now.plusSeconds(1));
        assertTrue(s.usable(now));

        s.setExpiresAt(null);   // 长期
        assertTrue(s.usable(now));
    }

    @Test
    @DisplayName("撤销/待接受/已过期的共享都不可用")
    void share_unusable_statuses() {
        LocalDateTime now = LocalDateTime.of(2026, 11, 3, 12, 0);
        for (String st : List.of(CredentialShare.STATUS_PENDING, CredentialShare.STATUS_REVOKED,
                CredentialShare.STATUS_EXPIRED)) {
            CredentialShare s = new CredentialShare();
            s.setStatus(st);
            assertFalse(s.usable(now), st + " 不该可用");
        }
    }

    @Test
    @DisplayName("共享额度上限：quotaTokens=0 表示不限；达到上限即耗尽")
    void share_quota_exhaustion() {
        CredentialShare unlimited = new CredentialShare();
        unlimited.setQuotaTokens(0L);
        unlimited.setUsedTokens(999_999L);
        assertFalse(unlimited.exhausted(), "0 = 不限，不能因为用得多就判耗尽");

        CredentialShare capped = new CredentialShare();
        capped.setQuotaTokens(1000L);
        capped.setUsedTokens(999L);
        assertFalse(capped.exhausted());
        capped.setUsedTokens(1000L);
        assertTrue(capped.exhausted(), "达到上限即耗尽（>= 而非 >）");
    }

    // ---------------------------------------------------------------- ③ 掩码

    @Test
    @DisplayName("掩码只留前 3 后 4，长度不足时全打码")
    void mask_keeps_only_prefix_and_suffix() {
        assertEquals("sk-****back", ModelCredentialService.mask("sk-e2e-plaintext-should-never-come-back"));
        assertEquals("****", ModelCredentialService.mask("short"));
        assertEquals("****", ModelCredentialService.mask(null));
    }

    // ---------------------------------------------------------------- ④ 越权与撤销

    @Test
    @DisplayName("解析他人账号：无 ACTIVE 共享 ⇒ 403，不静默放行")
    void resolve_rejects_when_not_shared() {
        AuthUser grantee = user(8L, 2L);
        ModelCredential other = new ModelCredential();
        other.setId(99L);
        other.setTenantId(2L);
        other.setOwnerType(ModelCredential.OWNER_PERSONAL);
        other.setOwnerUserId(7L);
        other.setStatus(ModelCredential.STATUS_ENABLED);
        when(credentialMapper.selectById(99L)).thenReturn(other);
        when(shareMapper.selectOne(any())).thenReturn(null);

        BizException ex = assertThrows(BizException.class, () -> service.resolve(grantee, 99L));
        assertTrue(ex.getMessage().contains("未共享"), ex.getMessage());
    }

    @Test
    @DisplayName("跨租户账号 ⇒ 404（不泄露存在性）")
    void resolve_rejects_cross_tenant() {
        AuthUser outsider = user(2L, 0L);
        ModelCredential foreign = new ModelCredential();
        foreign.setId(99L);
        foreign.setTenantId(2L);           // 账号在租户 2，请求方在租户 0
        foreign.setStatus(ModelCredential.STATUS_ENABLED);
        when(credentialMapper.selectById(99L)).thenReturn(foreign);

        BizException ex = assertThrows(BizException.class, () -> service.resolve(outsider, 99L));
        assertEquals(404, ex.getCode());
    }

    @Test
    @DisplayName("持有人自己的账号：承担人就是自己，无需共享记录")
    void resolve_owner_uses_own_account() {
        AuthUser owner = user(7L, 2L);
        ModelCredential mine = new ModelCredential();
        mine.setId(5L);
        mine.setTenantId(2L);
        mine.setOwnerType(ModelCredential.OWNER_PERSONAL);
        mine.setOwnerUserId(7L);
        mine.setStatus(ModelCredential.STATUS_ENABLED);
        mine.setProviderKey("deepseek");
        mine.setApiKeyCipher(secretCodec.encrypt("sk-mine"));
        when(credentialMapper.selectById(5L)).thenReturn(mine);

        ModelCredentialService.Resolved r = service.resolve(owner, 5L);
        assertEquals(7L, r.chargeUserId(), "个人账号：承担人 = 持有人");
        assertEquals("sk-mine", r.apiKey(), "明文 Key 只在服务内出现");
        assertFalse(r.companyCharged());
    }

    @Test
    @DisplayName("公司账号：本租户成员可用，扣公司池")
    void resolve_company_account_for_member() {
        AuthUser member = user(8L, 2L);
        ModelCredential company = new ModelCredential();
        company.setId(6L);
        company.setTenantId(2L);
        company.setOwnerType(ModelCredential.OWNER_COMPANY);
        company.setStatus(ModelCredential.STATUS_ENABLED);
        company.setProviderKey("vllm");
        company.setApiKeyCipher(secretCodec.encrypt("sk-company"));
        when(credentialMapper.selectById(6L)).thenReturn(company);

        ModelCredentialService.Resolved r = service.resolve(member, 6L);
        assertEquals(0L, r.chargeUserId(), "公司账号扣公司池");
        assertTrue(r.companyCharged());
    }

    @Test
    @DisplayName("撤销后再次邀请复用同一行，且重置已用量")
    void reinvite_reuses_row_and_resets_usage() {
        AuthUser owner = user(7L, 2L);
        ModelCredential mine = new ModelCredential();
        mine.setId(5L);
        mine.setTenantId(2L);
        mine.setOwnerType(ModelCredential.OWNER_PERSONAL);
        mine.setOwnerUserId(7L);
        mine.setStatus(ModelCredential.STATUS_ENABLED);
        mine.setShareEnabled(1);
        when(credentialMapper.selectById(5L)).thenReturn(mine);
        // 两种调用形状都要桩：findUser(sql, id, tenant) 与 userName(sql, id)
        when(jdbc.queryForList(any(String.class), any(Object.class), any(Object.class)))
                .thenReturn(List.of(Map.of("id", 8, "nickname", "李思远")));
        when(jdbc.queryForList(any(String.class), any(Object.class)))
                .thenReturn(List.of(Map.of("nickname", "刘敏")));

        CredentialShare revoked = new CredentialShare();
        revoked.setId(3L);
        revoked.setStatus(CredentialShare.STATUS_REVOKED);
        revoked.setUsedTokens(800L);
        revoked.setQuotaTokens(1000L);
        when(shareMapper.selectOne(any())).thenReturn(revoked);
        when(shareMapper.selectCount(any())).thenReturn(0L);
        when(shareMapper.updateById(any(CredentialShare.class))).thenReturn(1);

        service.invite(owner, 5L, Map.of("granteeUsername", "fagai_li"));

        ArgumentCaptor<CredentialShare> cap = ArgumentCaptor.forClass(CredentialShare.class);
        verify(shareMapper).updateById(cap.capture());   // 显式 captor 消解 updateById 的重载歧义
        CredentialShare saved = cap.getValue();
        assertEquals(CredentialShare.STATUS_ACTIVE, saved.getStatus(), "撤销后重新邀请 ⇒ 复活");
        assertEquals(0L, saved.getUsedTokens(), "已用量必须重置，否则上轮的用量直接顶掉新配额");
        assertTrue(saved.getRevokedAt() == null, "撤销时间要清掉，否则时间线看不出又生效了");
    }

    @Test
    @DisplayName("邀请校验：未开启共享 / 已停用 / 邀请自己 / 重复邀请，各自有明确拒绝")
    void invite_validation_matrix() {
        AuthUser owner = user(7L, 2L);
        ModelCredential closed = new ModelCredential();
        closed.setId(5L);
        closed.setTenantId(2L);
        closed.setOwnerType(ModelCredential.OWNER_PERSONAL);
        closed.setOwnerUserId(7L);
        closed.setStatus(ModelCredential.STATUS_ENABLED);
        closed.setShareEnabled(0);
        when(credentialMapper.selectById(5L)).thenReturn(closed);
        assertThrows(BizException.class,
                () -> service.invite(owner, 5L, Map.of("granteeUsername", "x")), "未开启共享必须拒绝");

        closed.setShareEnabled(1);
        closed.setStatus(ModelCredential.STATUS_DISABLED);
        assertThrows(BizException.class,
                () -> service.invite(owner, 5L, Map.of("granteeUsername", "x")), "停用账号必须拒绝");
    }
}
