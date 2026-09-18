package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.client.RepoProviderClient;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteeAccount;
import cn.aioa.gitee.entity.GiteeOauthState;
import cn.aioa.gitee.mapper.GiteeAccountMapper;
import cn.aioa.gitee.mapper.GiteeOauthStateMapper;
import cn.aioa.gitee.support.GiteeCrypto;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Gitee 账号绑定服务（OAuth2 授权码模式）。
 *
 * <p><b>为什么必须走授权码而不是让用户贴私人令牌</b>：私人令牌无法刷新、权限是全量、
 * 用户无法自行撤销；授权码换来的是「可刷新 + 可撤销 + 有 scope」的令牌，
 * 且平台不接触用户密码。</p>
 *
 * <p><b>state 的三重作用</b>：① 防 CSRF（回调必须带回服务端发出的 state）；
 * ② 承载身份（回调时没有 JWT，只能靠 state 反查是哪个用户发起的绑定）；
 * ③ 一次性（consumed 置位 + 过期时间），防止重放。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeAccountService {

    /** state 有效期：10 分钟足够用户完成授权，且暴露窗口足够小。 */
    private static final long STATE_TTL_SECONDS = 600;

    /**
     * 「既有绑定也可能是桩造的」uid 上界：小于它视为桩身份（可被沙箱回调覆盖）。
     * 实测桩签发 5 位 uid（42040–42891），真实账号 8 位（14032724）。见 {@link #clobberRealBinding}。
     */
    static final long STUB_UID_CEILING = 1_000_000L;

    private final GiteeOauthStateMapper stateMapper;
    private final GiteeAccountMapper accountMapper;
    private final RepoProviderClient client;
    private final GiteeCrypto crypto;
    private final RepoProviderSettings props;

    // ======================================================================
    // 发起绑定
    // ======================================================================

    /**
     * 生成授权跳转地址。
     *
     * <p>返回 {@code url} 由前端 {@code window.location.href = url} 打开（Gitee 不允许 iframe）。</p>
     */
    public Map<String, Object> bindUrl(AuthUser user) {
        assertBindable();
        String state = UUID.randomUUID().toString().replace("-", "");

        GiteeOauthState row = new GiteeOauthState();
        row.setState(state);
        row.setTenantId(user.getTenantId());
        row.setUserId(user.getUserId());
        row.setRedirectUri(props.getRedirectUri());
        row.setConsumed(false);
        row.setExpiresAt(LocalDateTime.now().plusSeconds(STATE_TTL_SECONDS));
        row.setCreatedAt(LocalDateTime.now());
        stateMapper.insert(row);

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("url", client.authorizeUrl(state));
        m.put("state", state);
        m.put("expiresInSeconds", STATE_TTL_SECONDS);
        // fail-loud：授权域若是本地桩/代理，必须让调用方看得见，否则「绑定成功」会误导人
        // （用户以为完成了 Gitee 授权，实际是桩签发了一个假身份）。
        boolean sandbox = client.authorizeHostIsSandbox();
        m.put("authorizeHost", client.authorizeHost());
        m.put("sandbox", sandbox);
        if (sandbox) {
            m.put("warning", props.sandboxAuthorizeWarning(client.authorizeHost()));
        }
        m.put("note", "请在浏览器打开该地址完成授权；授权后回到平台即自动完成绑定");
        return m;
    }

    /**
     * 授权回调：校验 state → 换令牌 → 拉取用户信息 → 落库（已绑定则更新）。
     *
     * @return 绑定结果视图（不含任何令牌字段）
     */
    @Transactional
    public Map<String, Object> callback(String code, String state) {
        if (!StringUtils.hasText(code) || !StringUtils.hasText(state)) {
            throw BizException.badRequest("授权回调缺少 code 或 state");
        }
        GiteeOauthState st = stateMapper.selectOne(new LambdaQueryWrapper<GiteeOauthState>()
                .eq(GiteeOauthState::getState, state).last("limit 1"));
        if (st == null) {
            throw BizException.badRequest("授权状态不存在或已被清理，请重新发起绑定");
        }
        if (Boolean.TRUE.equals(st.getConsumed())) {
            throw BizException.badRequest("该授权链接已被使用，请重新发起绑定");
        }
        if (st.getExpiresAt() != null && st.getExpiresAt().isBefore(LocalDateTime.now())) {
            throw BizException.badRequest("授权链接已过期，请重新发起绑定");
        }
        // 先置位再换令牌：即使后续失败，链接也不可复用（防重放）
        st.setConsumed(true);
        stateMapper.updateById(st);

        Map<String, Object> tokenResp = client.exchangeCode(code);
        String accessToken = str(tokenResp.get("access_token"));
        if (!StringUtils.hasText(accessToken)) {
            throw BizException.badRequest(props.providerLabel() + " 未返回 access_token，授权可能被拒绝");
        }
        String refreshToken = str(tokenResp.get("refresh_token"));
        LocalDateTime expiresAt = expiryOf(tokenResp);

        // 用新令牌取真实身份：不能信前端传来的 uid/login
        Map<String, Object> me = client.getUser(accessToken);
        Long giteeUid = asLong(me.get("id"));
        String giteeUsername = str(me.get("login"));
        if (giteeUid == null || !StringUtils.hasText(giteeUsername)) {
            throw BizException.badRequest("无法获取 " + props.providerLabel() + " 用户身份（令牌 scope 权限不足）");
        }

        GiteeAccount acc = accountMapper.selectOne(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, st.getTenantId())
                .eq(GiteeAccount::getUserId, st.getUserId())
                .eq(GiteeAccount::getProvider, providerName())
                .last("limit 1"));
        boolean created = acc == null;

        // 回归接线（沙箱）不得覆盖「看起来是真实账号」的既有绑定。
        // 桩会签发一个假身份回跳，覆盖后真实令牌被换成假令牌 —— **不可逆**的数据损坏，
        // 而且覆盖者与被覆盖者都是「绑定成功」的合法返回，事后无法分辨。
        if (!created && clobberRealBinding(acc.getGiteeUid(), giteeUid, client.authorizeHostIsSandbox())) {
            throw BizException.badRequest("当前为端到端回归接线（授权域 " + client.authorizeHost()
                    + " 非官方站点），拒绝用它覆盖已存在的真实绑定：原 uid=" + acc.getGiteeUid()
                    + "，本次 uid=" + giteeUid + "。如需更换账号，请在真实授权域下先解绑再绑定。");
        }

        if (created) {
            acc = new GiteeAccount();
            acc.setTenantId(st.getTenantId());
            acc.setUserId(st.getUserId());
            acc.setCreatedAt(LocalDateTime.now());
        }
        // 绑定行按托管方归属（V54）：写库时必须打上当前 provider，
        // 否则下次查询会以「别的平台的身份」被取到（uid 相撞/登录名不存在/密文解不开）。
        acc.setProvider(providerName());
        acc.setGiteeUid(giteeUid);
        acc.setGiteeUsername(giteeUsername);
        acc.setGiteeName(str(me.get("name")));
        acc.setAvatarUrl(str(me.get("avatar_url")));
        acc.setAccessToken(crypto.encrypt(accessToken));
        // 刷新可能不返回新的 refresh_token：此时必须保留旧的，否则下次无法续期
        acc.setRefreshToken(StringUtils.hasText(refreshToken)
                ? crypto.encrypt(refreshToken) : acc.getRefreshToken());
        acc.setTokenExpiresAt(expiresAt);
        String scope = str(tokenResp.get("scope"));
        acc.setScope(scope);
        acc.setBoundAt(LocalDateTime.now());
        acc.setUpdatedAt(LocalDateTime.now());

        // 只记长度、不记值：托管方令牌的**形态**是会变的 —— Gitee 是 32~40 字符短串，
        // Gitea 是 600~1000 字符的 JWT。长度打在**写库之前**，这样列宽不够时日志里
        // 直接能看到实际规模，而不是只拿到一句 "Data too long for column"（V55 之前正是如此）。
        log.info("{} 绑定：令牌长度 token={} refresh={} scope={}",
                props.providerLabel(), accessToken.length(),
                refreshToken == null ? 0 : refreshToken.length(),
                scope == null ? 0 : scope.length());

        if (created) {
            accountMapper.insert(acc);
        } else {
            accountMapper.updateById(acc);
        }
        log.info("Gitee 绑定成功 tenant={} user={} gitee={}({})",
                acc.getTenantId(), acc.getUserId(), giteeUsername, giteeUid);

        Map<String, Object> m = new LinkedHashMap<>();
        m.put("bound", true);
        m.put("created", created);
        m.put("giteeUid", giteeUid);
        m.put("giteeUsername", giteeUsername);
        m.put("giteeName", acc.getGiteeName());
        m.put("scope", acc.getScope());
        m.put("expiresAt", expiresAt);
        return m;
    }

    // ======================================================================
    // 查询与解绑
    // ======================================================================

    /** 当前用户的绑定状态（永远不返回令牌原文）。 */
    public Map<String, Object> myBinding(AuthUser user) {
        GiteeAccount acc = accountMapper.selectOne(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, user.getTenantId())
                .eq(GiteeAccount::getUserId, user.getUserId())
                .eq(GiteeAccount::getProvider, providerName())
                .last("limit 1"));
        return toView(acc);
    }

    /** 脱敏视图：只暴露身份与有效期，令牌一律不出服务端。 */
    public Map<String, Object> toView(GiteeAccount acc) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("enabled", props.isEnabled());
        m.put("bound", acc != null);
        if (acc == null) {
            return m;
        }
        m.put("giteeUid", acc.getGiteeUid());
        m.put("giteeUsername", acc.getGiteeUsername());
        m.put("giteeName", acc.getGiteeName());
        m.put("avatarUrl", acc.getAvatarUrl());
        m.put("scope", acc.getScope());
        m.put("boundAt", acc.getBoundAt());
        m.put("refreshedAt", acc.getRefreshedAt());
        m.put("tokenExpiresAt", acc.getTokenExpiresAt());
        // 「是否已过期」交给前端展示，避免前端自己算时间时区出错
        m.put("tokenExpired", acc.getTokenExpiresAt() != null
                && acc.getTokenExpiresAt().isBefore(LocalDateTime.now()));
        m.put("hasRefreshToken", StringUtils.hasText(acc.getRefreshToken()));
        return m;
    }

    /**
     * 解绑：物理删除本地令牌（不调用 Gitee 撤销接口 —— 用户可在 Gitee 侧自行撤销授权）。
     *
     * <p>只解绑**当前托管方**的绑定：同一用户在 Gitea 上的身份与在 Gitee 上的身份
     * 是两条互不相干的行（V54），解绑其一不该把另一条也删掉。</p>
     */
    @Transactional
    public void unbind(AuthUser user) {
        int n = accountMapper.delete(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, user.getTenantId())
                .eq(GiteeAccount::getUserId, user.getUserId())
                .eq(GiteeAccount::getProvider, providerName()));
        if (n == 0) {
            throw BizException.badRequest("当前账号尚未绑定 " + props.providerLabel());
        }
        log.info("Gitee 解绑 tenant={} user={} provider={}", user.getTenantId(), user.getUserId(), providerName());
    }

    /** 当前托管方标识（与写入端同一来源）。 */
    private String providerName() {
        return props.providerName();
    }

    // ======================================================================
    // 内部
    // ======================================================================

    /** 未启用或未配置 client_id 时给出**可执行**的报错，而不是后续 401 让人误判。 */
    private void assertBindable() {
        if (!props.isEnabled()) {
            throw BizException.badRequest(props.hintDisabled());
        }
        if (!props.oauthConfigured()) {
            throw BizException.badRequest(props.hintOauthMissing());
        }
        if (!StringUtils.hasText(props.getRedirectUri())) {
            throw BizException.badRequest(props.hintRedirectMissing());
        }
    }

    /** expires_in 为秒；缺失时返回 null（按「不过期」处理，见 GiteeTokenService）。 */
    LocalDateTime expiryOf(Map<String, Object> resp) {
        Long sec = asLong(resp.get("expires_in"));
        return sec == null || sec <= 0 ? null : LocalDateTime.now().plusSeconds(sec);
    }

    /**
     * 「本次回调会不会用沙箱假身份覆盖一个真实绑定」。
     *
     * <p><b>为什么必须拦</b>：两条路径的返回值都叫「绑定成功」，覆盖后**无从分辨**，
     * 真实令牌已被换成假令牌，属于不可逆的数据损坏。2026-09-18 之前只能靠
     * 「跑桩套件前先备份 `gitee_account` 并事后比对」来绕，人一忘就出事。</p>
     *
     * <p><b>真实账号的判据（启发式）</b>：本地桩签发的是**5 位** uid（实测 42040–42891），
     * 而真实 Gitee 账号 uid 是 **8 位**（实测 14032724）。故以 {@link #STUB_UID_CEILING}
     * 为界：既有行的 uid 小于它 ⇒ 认为既有绑定本来也是桩造出来的，可被桩覆盖
     * （否则桩套件每轮重启后 uid 会变，重绑全被拦住）。</p>
     *
     * <p><b>该启发式的失效方向是「fail-open」</b>：若某个真实老账号的 uid 恰好在 7 位以下，
     * 它不会被保护 —— 与改造前的行为一致，不会比原来更糟。彻底修法是给绑定行加一个
     * `sandbox` 列，由写入方如实标注来源，再按列判定（已在交付说明中列为后续项）。</p>
     *
     * @param existingUid 既有绑定行的 uid（为 null 表示无从判断）
     * @param incomingUid 本次回调拿到的 uid
     * @param sandbox     本次授权域是否为非官方站点（沙箱/桩）
     */
    static boolean clobberRealBinding(Long existingUid, Long incomingUid, boolean sandbox) {
        if (!sandbox || existingUid == null) {
            return false;                       // 真实授权域的换号重绑是合法操作，不拦
        }
        if (existingUid.equals(incomingUid)) {
            return false;                       // 同一个账号重新授权，不算覆盖
        }
        return existingUid >= STUB_UID_CEILING;
    }

    static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    static Long asLong(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.valueOf(String.valueOf(o).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
