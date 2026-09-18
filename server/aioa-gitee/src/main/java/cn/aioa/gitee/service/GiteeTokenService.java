package cn.aioa.gitee.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.gitee.client.RepoProviderException;
import cn.aioa.gitee.client.RepoProviderClient;
import cn.aioa.gitee.config.RepoProviderSettings;
import cn.aioa.gitee.entity.GiteeAccount;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.entity.GiteeTenantConfig;
import cn.aioa.gitee.mapper.GiteeAccountMapper;
import cn.aioa.gitee.mapper.GiteeTenantConfigMapper;
import cn.aioa.gitee.support.GiteeCrypto;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Gitee 令牌服务：取用 + **自动续期**。
 *
 * <p><b>为什么要「提前 5 分钟」刷新而不是等到 401</b>：等到 401 再刷，意味着这一次业务调用
 * 已经失败；对于「建仓 + 配 Webhook + 同步成员」这种多步任务，一次失败就要整轮重试，
 * 放大限流压力。提前刷新把过期变成对业务透明。</p>
 *
 * <p><b>为什么要单飞（single-flight）</b>：Gitee 刷新令牌会**轮换 refresh_token**
 * —— 两个并发任务同时用同一个 refresh_token 去刷，只有一个会成功，另一个拿到
 * {@code invalid_grant}，并且会把已轮换的新令牌覆盖成旧值，导致绑定直接失效。
 * 因此同一用户的刷新必须串行（按 userId 加锁）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GiteeTokenService {

    /** 提前刷新窗口（秒）。 */
    private static final long REFRESH_AHEAD_SECONDS = 300;

    private final GiteeAccountMapper accountMapper;
    private final RepoProviderClient client;
    private final GiteeCrypto crypto;
    private final RepoProviderSettings props;
    private final GiteeTenantConfigMapper tenantConfigMapper;

    /** 按用户串行刷新（防止 refresh_token 轮换竞争）。 */
    private final Map<Long, Object> locks = new ConcurrentHashMap<>();

    /**
     * 查询**当前托管方**下的绑定（未绑定时为空）。
     *
     * <p>必须带 {@code provider} 条件：{@code gitee_account} 存的是某一平台的身份
     * （uid / 登录名 / 该平台密钥加密的令牌）。不过滤就会把 Gitee 的行当成 Gitea 的行，
     * 后果实测为：解密 Tag mismatch → 建项目 500；登录名被拿去 Gitea 协作者接口 → 404。</p>
     */
    public GiteeAccount findAccount(Long tenantId, Long userId) {
        return accountMapper.selectOne(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, tenantId)
                .eq(GiteeAccount::getUserId, userId)
                .eq(GiteeAccount::getProvider, providerName())
                .last("limit 1"));
    }

    /** 按 Gitee uid 反查绑定（Webhook 身份映射用）。 */
    public GiteeAccount findByGiteeUid(Long tenantId, Long giteeUid) {
        if (giteeUid == null) {
            return null;
        }
        return accountMapper.selectOne(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, tenantId)
                .eq(GiteeAccount::getGiteeUid, giteeUid)
                .eq(GiteeAccount::getProvider, providerName())
                .last("limit 1"));
    }

    /**
     * 列出该租户下**当前托管方**的所有绑定记录。
     *
     * <p>用于按 Gitee 用户名反查（Webhook 的身份映射兜底路径）与周期性校准。
     * 绑定规模 = 租户人数，量级可控；仍加租户条件避免全表扫描。</p>
     */
    public java.util.List<GiteeAccount> allAccounts(Long tenantId) {
        return accountMapper.selectList(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, tenantId)
                .eq(GiteeAccount::getProvider, providerName()));
    }

    /**
     * 按 Gitee 登录名反查绑定（Webhook 身份映射：事件里只有 login，没有 uid 时用）。
     */
    public GiteeAccount findByUsername(Long tenantId, String giteeUsername) {
        if (!StringUtils.hasText(giteeUsername)) {
            return null;
        }
        return accountMapper.selectOne(new LambdaQueryWrapper<GiteeAccount>()
                .eq(GiteeAccount::getTenantId, tenantId)
                .eq(GiteeAccount::getProvider, providerName())
                .apply("lower(gitee_username) = {0}", giteeUsername.trim().toLowerCase())
                .last("limit 1"));
    }

    /** 当前托管方标识（写库与查询共用同一来源，避免两处口径漂移）。 */
    public String providerName() {
        return props.providerName();
    }

    /**
     * 取该用户可用的 access_token（必要时自动刷新）。
     *
     * <p><b>个人绑定不可解密时回落企业令牌，而不是让请求 500</b>：绑定行的密文由
     * 写入时的托管方密钥加密；一旦 {@code aioa.repo.provider} 被切换，老绑定的密文
     * 在新密钥下必然 Tag mismatch。此时企业令牌是**完全可用**的（本就设计为回落源），
     * 把它浪费掉、反而给用户一个「服务内部错误」，是纯粹的负价值。
     * 解不开的行按「本平台下没有这条绑定」处理，并留 WARN 便于排查。</p>
     *
     * @throws BizException 未绑定且无企业令牌（提示用户重新绑定）
     */
    public String requireAccessToken(Long tenantId, Long userId) {
        GiteeAccount acc = findAccount(tenantId, userId);
        if (acc != null) {
            String personal = decryptTolerant(acc, "user=" + userId);
            if (personal != null) {
                return personal;
            }
        }
        // 个人未绑定（或本平台下不可用）→ 回落企业令牌（组织级）
        String ent = enterpriseToken(tenantId);
        if (ent != null) {
            return ent;
        }
        if (acc != null) {
            throw BizException.badRequest(staleBindingHint());
        }
        throw BizException.badRequest("当前账号尚未绑定 " + props.providerLabel()
                    + "，请先在「我的 " + props.providerLabel() + " 账号」完成授权");
    }

    /** 取项目的可用令牌：用**项目创建者**的身份（建仓与后续维护都由他发起）。 */
    public String requireAccessTokenForProject(GiteeProject project) {
        if (project.getCreatedBy() == null) {
            throw BizException.badRequest("项目缺少创建者，无法确定用哪个 " + props.providerLabel() + " 身份操作");
        }
        GiteeAccount acc = findAccount(project.getTenantId(), project.getCreatedBy());
        if (acc != null) {
            String personal = decryptTolerant(acc, "project=" + project.getId());
            if (personal != null) {
                return personal;
            }
        }
        // 个人未绑定（或本平台下不可用）→ 回落企业令牌
        String ent = enterpriseToken(project.getTenantId());
        if (ent != null) {
            return ent;
        }
        if (acc != null) {
            throw BizException.badRequest(staleBindingHint());
        }
        throw BizException.badRequest("当前账号尚未绑定 " + props.providerLabel()
                    + "，请先在「我的 " + props.providerLabel() + " 账号」完成授权");
    }

    /**
     * 取个人绑定的令牌；**解密失败返回 null**（而不是抛异常）。
     *
     * <p>只吞「密文解不开」这一类失败。{@link BizException}（令牌确实失效、需要用户
     * 重新授权）照旧抛出 —— 那不是「换平台遗留」，回落企业令牌会把真实故障盖掉。</p>
     */
    private String decryptTolerant(GiteeAccount acc, String who) {
        try {
            return validToken(acc);
        } catch (IllegalStateException e) {
            log.warn("{} 的个人绑定令牌无法用当前托管方({})的密钥解密，本次按未绑定处理并回落企业令牌："
                            + "accountId={} msg={}",
                    who, providerName(), acc.getId(), e.getMessage());
            return null;
        }
    }

    /** 「绑定属于别的托管方 / 密钥已变」这类不可用绑定的可执行提示。 */
    private String staleBindingHint() {
        return "当前账号在本平台的绑定令牌无法解密（通常是切换托管方后遗留的旧绑定，"
                + "或 " + props.tokenEncKeyProperty() + " 被变更）。"
                + "请在企业侧配置组织级令牌，或先在「我的 " + props.providerLabel() + " 账号」解绑后重新授权。";
    }


    /**
     * 企业（组织级）令牌回落源：当 {@code gitee_tenant_config} 有行、{@code init_status='ACTIVE'}、
     * 且 {@code access_token} 非空时解密返回；否则返回 null。
     *
     * <p>企业令牌<b>没有 refresh_token</b>，绝不走 {@link #validToken} 的刷新逻辑，直接返回原值。
     * 解密失败（密钥变更/损坏）包装为清晰业务错误，由调用方提示重新初始化。</p>
     */
    public String enterpriseToken(Long tenantId) {
        if (tenantId == null) {
            return null;
        }
        GiteeTenantConfig row = tenantConfigMapper.selectOne(new LambdaQueryWrapper<GiteeTenantConfig>()
                .eq(GiteeTenantConfig::getTenantId, tenantId)
                .last("limit 1"));
        if (row == null || !"ACTIVE".equals(row.getInitStatus())
                || !StringUtils.hasText(row.getAccessToken())) {
            return null;
        }
        try {
            return crypto.decrypt(row.getAccessToken());
        } catch (Exception e) {
            // 解密处包装：首次使用企业令牌即失败，给出明确指引（不改既有个人令牌消息）
            throw BizException.badRequest("企业访问令牌已失效，请重新初始化");
        }
    }

    /**
     * 校验并按需刷新。
     *
     * <p>令牌无过期时间（{@code tokenExpiresAt} 为空）时按「不过期」处理 —— Gitee 的
     * 私人令牌确实可能长期有效，不能因为「没有过期时间」就当成已过期而疯狂刷新。</p>
     */
    public String validToken(GiteeAccount acc) {
        String token = crypto.decrypt(acc.getAccessToken());
        if (!StringUtils.hasText(token)) {
            throw BizException.badRequest(props.providerLabel() + " 绑定缺少 access_token，请重新授权");
        }
        LocalDateTime exp = acc.getTokenExpiresAt();
        if (exp == null || exp.isAfter(LocalDateTime.now().plusSeconds(REFRESH_AHEAD_SECONDS))) {
            return token;
        }
        // 进入刷新窗口：串行刷新
        synchronized (locks.computeIfAbsent(acc.getUserId(), k -> new Object())) {
            // 双重检查：等锁期间可能已被其他线程刷新
            GiteeAccount fresh = accountMapper.selectById(acc.getId());
            if (fresh == null) {
                throw BizException.badRequest(props.providerLabel() + " 绑定已解除，请重新授权");
            }
            String freshToken = crypto.decrypt(fresh.getAccessToken());
            if (fresh.getTokenExpiresAt() != null
                    && fresh.getTokenExpiresAt().isAfter(LocalDateTime.now().plusSeconds(REFRESH_AHEAD_SECONDS))) {
                return freshToken;
            }
            return refresh(fresh);
        }
    }

    /** 执行刷新并落库（轮换 refresh_token）。 */
    private String refresh(GiteeAccount acc) {
        String rt = crypto.decrypt(acc.getRefreshToken());
        if (!StringUtils.hasText(rt)) {
            throw BizException.badRequest(props.providerLabel() + " 授权已过期且无 refresh_token，请重新授权");
        }
        Map<String, Object> resp;
        try {
            resp = client.refreshToken(rt);
        } catch (RepoProviderException e) {
            // 刷新失败绝大多数是 refresh_token 失效（用户撤销授权 / 超期）→ 必须让用户重来
            log.warn("Gitee 刷新令牌失败 user={} status={} msg={}", acc.getUserId(), e.getStatus(), e.getMessage());
            throw BizException.badRequest(props.providerLabel() + " 授权已失效，请重新授权绑定：" + e.getMessage());
        }
        String newAccess = str(resp.get("access_token"));
        String newRefresh = str(resp.get("refresh_token"));
        if (!StringUtils.hasText(newAccess)) {
            throw BizException.badRequest(props.providerLabel() + " 刷新令牌未返回 access_token，请重新授权");
        }
        GiteeAccount upd = new GiteeAccount();
        upd.setId(acc.getId());
        upd.setAccessToken(crypto.encrypt(newAccess));
        // 轮换：Gitee 会返回新的 refresh_token，必须覆盖，否则下次刷新必失败
        if (StringUtils.hasText(newRefresh)) {
            upd.setRefreshToken(crypto.encrypt(newRefresh));
        }
        upd.setTokenExpiresAt(expiryOf(resp));
        upd.setRefreshedAt(LocalDateTime.now());
        upd.setUpdatedAt(LocalDateTime.now());
        accountMapper.updateById(upd);
        log.info("Gitee 令牌已自动续期 user={} expiresAt={}", acc.getUserId(), upd.getTokenExpiresAt());
        return newAccess;
    }

    /** 由 Gitee 响应计算过期时间（{@code expires_in} 秒）。 */
    public LocalDateTime expiryOf(Map<String, Object> resp) {
        Object v = resp == null ? null : resp.get("expires_in");
        if (v == null) {
            return null;
        }
        try {
            long sec = Long.parseLong(String.valueOf(v).trim());
            return sec > 0 ? LocalDateTime.now().plusSeconds(sec) : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** 该租户的配置是否可用于真实调用（enabled + 有 clientId）。 */
    public void assertEnabled() {
        if (!props.isEnabled()) {
            throw BizException.badRequest(props.providerLabel() + " 联动未启用：请配置 " + props.configKeyPrefix() + ".enabled=true 与 client_id/client_secret");
        }
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }
}
