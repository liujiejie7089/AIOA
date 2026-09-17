package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.client.GiteeClient;
import cn.aioa.gitee.config.GiteeProperties;
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

    private final GiteeOauthStateMapper stateMapper;
    private final GiteeAccountMapper accountMapper;
    private final GiteeClient client;
    private final GiteeCrypto crypto;
    private final GiteeProperties props;

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
            m.put("warning", "当前授权域为 " + client.authorizeHost()
                    + "（非 gitee.com），本次授权不会跳转到真实 Gitee。"
                    + "如需真实授权，请将 aioa.gitee.oauth-authorize-base-url"
                    + "（环境变量 AIOA_GITEE_OAUTH_AUTHORIZE_URL）配置为 https://gitee.com 后重试。");
        }
        m.put("note", "请在浏览器打开该地址完成 Gitee 授权；授权后回到平台即自动完成绑定");
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
            throw BizException.badRequest("Gitee 未返回 access_token，授权可能被拒绝");
        }
        String refreshToken = str(tokenResp.get("refresh_token"));
        LocalDateTime expiresAt = expiryOf(tokenResp);

        // 用新令牌取真实身份：不能信前端传来的 uid/login
        Map<String, Object> me = client.getUser(accessToken);
        Long giteeUid = asLong(me.get("id"));
        String giteeUsername = str(me.get("login"));
        if (giteeUid == null || !StringUtils.hasText(giteeUsername)) {
            throw BizException.badRequest("无法获取 Gitee 用户身份（可能 scope 缺少 user_info）");
        }

        GiteeAccount acc = accountMapper.selectOne(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, st.getTenantId())
                .eq(GiteeAccount::getUserId, st.getUserId())
                .last("limit 1"));
        boolean created = acc == null;
        if (created) {
            acc = new GiteeAccount();
            acc.setTenantId(st.getTenantId());
            acc.setUserId(st.getUserId());
            acc.setCreatedAt(LocalDateTime.now());
        }
        acc.setGiteeUid(giteeUid);
        acc.setGiteeUsername(giteeUsername);
        acc.setGiteeName(str(me.get("name")));
        acc.setAvatarUrl(str(me.get("avatar_url")));
        acc.setAccessToken(crypto.encrypt(accessToken));
        // 刷新可能不返回新的 refresh_token：此时必须保留旧的，否则下次无法续期
        acc.setRefreshToken(StringUtils.hasText(refreshToken)
                ? crypto.encrypt(refreshToken) : acc.getRefreshToken());
        acc.setTokenExpiresAt(expiresAt);
        acc.setScope(str(tokenResp.get("scope")));
        acc.setBoundAt(LocalDateTime.now());
        acc.setUpdatedAt(LocalDateTime.now());

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

    /** 解绑：物理删除本地令牌（不调用 Gitee 撤销接口 —— 用户可在 Gitee 侧自行撤销授权）。 */
    @Transactional
    public void unbind(AuthUser user) {
        int n = accountMapper.delete(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, user.getTenantId())
                .eq(GiteeAccount::getUserId, user.getUserId()));
        if (n == 0) {
            throw BizException.badRequest("当前账号尚未绑定 Gitee");
        }
        log.info("Gitee 解绑 tenant={} user={}", user.getTenantId(), user.getUserId());
    }

    // ======================================================================
    // 内部
    // ======================================================================

    /** 未启用或未配置 client_id 时给出**可执行**的报错，而不是后续 401 让人误判。 */
    private void assertBindable() {
        if (!props.isEnabled()) {
            throw BizException.badRequest("Gitee 集成未启用（aioa.gitee.enabled=false）");
        }
        if (!StringUtils.hasText(props.getClientId()) || !StringUtils.hasText(props.getClientSecret())) {
            throw BizException.badRequest("Gitee OAuth 应用未配置（缺 aioa.gitee.client-id / client-secret）");
        }
        if (!StringUtils.hasText(props.getRedirectUri())) {
            throw BizException.badRequest("Gitee OAuth 回调地址未配置（aioa.gitee.redirect-uri）");
        }
    }

    /** expires_in 为秒；缺失时返回 null（按「不过期」处理，见 GiteeTokenService）。 */
    LocalDateTime expiryOf(Map<String, Object> resp) {
        Long sec = asLong(resp.get("expires_in"));
        return sec == null || sec <= 0 ? null : LocalDateTime.now().plusSeconds(sec);
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
