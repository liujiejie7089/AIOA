package cn.aioa.gitee.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 沙箱回调覆盖真实绑定的守卫。
 *
 * <p>这是**不可逆数据损坏**的唯一防线：真实令牌被换成桩签发的假令牌后，
 * 两条路径的返回都叫「绑定成功」，事后无从分辨。所以四种组合必须逐一钉死。</p>
 */
class GiteeAccountClobberGuardTest {

    private static final long REAL_UID = 14032724L;   // 实测真实账号 uid（8 位）
    private static final long STUB_UID = 42366L;      // 实测桩签发 uid（5 位）

    @Test
    @DisplayName("沙箱 + 既有是真实账号 + uid 不同 ⇒ 必须拦（这是唯一要防的场景）")
    void sandboxMustNotClobberRealBinding() {
        assertTrue(GiteeAccountService.clobberRealBinding(REAL_UID, STUB_UID, true));
    }

    @Test
    @DisplayName("沙箱 + 同一个账号重新授权 ⇒ 不拦（否则桩套件重跑必红）")
    void sandboxMayRefreshSameAccount() {
        assertFalse(GiteeAccountService.clobberRealBinding(STUB_UID, STUB_UID, true));
        assertFalse(GiteeAccountService.clobberRealBinding(REAL_UID, REAL_UID, true));
    }

    @Test
    @DisplayName("沙箱 + 既有也是桩身份（uid 变过）⇒ 不拦（桩重启后 uid 会变，重绑是常态）")
    void sandboxMayClobberStubBinding() {
        assertFalse(GiteeAccountService.clobberRealBinding(STUB_UID, 42891L, true));
    }

    @Test
    @DisplayName("真实授权域下换号重绑 ⇒ 不拦（这是合法操作，不能因噎废食）")
    void realDomainMayRebindAnotherAccount() {
        assertFalse(GiteeAccountService.clobberRealBinding(REAL_UID, STUB_UID, false));
    }

    @Test
    @DisplayName("既有行没有 uid（历史脏数据）⇒ 不拦，但也不视为真实账号")
    void missingExistingUidIsNotProtected() {
        assertFalse(GiteeAccountService.clobberRealBinding(null, STUB_UID, true));
    }

    @Test
    @DisplayName("门槛常数与实测一致：桩 uid 在门槛下、真实 uid 在上")
    void ceilingMatchesObservedData() {
        assertTrue(STUB_UID < GiteeAccountService.STUB_UID_CEILING);
        assertTrue(REAL_UID >= GiteeAccountService.STUB_UID_CEILING);
    }
}
