package cn.aios.admin.wecom;

import cn.aios.admin.service.AuthService;
import cn.aios.admin.mapper.ConnectorTenantConfigReadMapper;
import cn.aios.admin.mapper.WeComLoginBindingMapper;
import cn.aios.admin.mapper.WeComLoginPendingMapper;
import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.common.wecom.WeComAuthClient;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * 企业微信 OAuth 网页授权「静默登录」（V100，docs/58 §3.3 的登录向复用）。
 *
 * <p><b>用户零填写</b>：应用凭据来自租户级 {@code connector_tenant_config}（管理端
 * 「连接器配置」页）或平台级 {@code aios.connector.wechat-work.*}，用户端只看到一个
 * 「企业微信登录」按钮。scope 固定 {@code snsapi_privateinfo}（要拿 user_ticket →
 * getuserdetail → biz_mail 做账号绑定匹配）。</p>
 *
 * <p><b>流程</b>：start 生成一次性 state → 302 授权页 → callback 校验 state →
 * code 换 userid/user_ticket → getuserdetail 拿 biz_mail → 命中
 * {@link WeComLoginBinding} 直接由 {@code AuthService} 签发本地令牌（302 回 H5 带
 * hash 令牌）；未命中 → 身份存 {@link WeComLoginPending}，302 回 H5 引导本地登录，
 * 登录成功后 {@link #bind} 建立绑定，下次起静默登录。</p>
 *
 * <p><b>安全</b>：state 一次性（used_at 即废）+ 10 分钟 TTL；伪造 state 绝不换身份、
 * 绝不写绑定；corpSecret / access_token / user_ticket 只在后端内存，不进日志、不下发前端。</p>
 */
@Slf4j
@Service
public class WeComLoginService {

    private static final String CODE = "wechat_work";
    private static final String WEB_AUTH_BASE = "https://open.weixin.qq.com/connect/oauth2/authorize";
    private static final Duration STATE_TTL = Duration.ofMinutes(10);
    /** 登录发生在租户上下文之前，凭据/绑定统一走平台级租户（0）。 */
    private static final long PLATFORM_TENANT_ID = 0L;

    private final WeComLoginPendingMapper pendingMapper;
    private final WeComLoginBindingMapper bindingMapper;
    private final ConnectorTenantConfigReadMapper tenantConfigMapper;
    private final WeComPlatformCredentials platformCreds;
    private final SecretCodec secretCodec;
    private final WeComLoginProperties props;
    private final AuthService authService;
    private final WeComAuthClient weComAuth = new WeComAuthClient();
    private final ObjectMapper objectMapper = new ObjectMapper();

    public WeComLoginService(WeComLoginPendingMapper pendingMapper,
                             WeComLoginBindingMapper bindingMapper,
                             ConnectorTenantConfigReadMapper tenantConfigMapper,
                             WeComPlatformCredentials platformCreds,
                             SecretCodec secretCodec,
                             WeComLoginProperties props,
                             AuthService authService) {
        this.pendingMapper = pendingMapper;
        this.bindingMapper = bindingMapper;
        this.tenantConfigMapper = tenantConfigMapper;
        this.platformCreds = platformCreds;
        this.secretCodec = secretCodec;
        this.props = props;
        this.authService = authService;
    }

    /** 应用凭据（租户级优先，平台级回退）。三者齐备才算就绪。 */
    public record Creds(String corpId, String agentId, String corpSecret) {
    }

    /** 当前租户的企微应用凭据；未配齐返回 null。 */
    public Creds creds(Long tenantId) {
        try {
            String secretJson = tenantConfigMapper.selectActiveSecretJson(tenantId, CODE);
            if (secretJson != null && !secretJson.isBlank()) {
                JsonNode n = objectMapper.readTree(secretCodecDecrypt(secretJson));
                String corpId = n.path("corpId").asText("");
                String agentId = n.path("agentId").asText("");
                String corpSecret = n.path("corpSecret").asText("");
                if (!corpId.isBlank() && !agentId.isBlank() && !corpSecret.isBlank()) {
                    return new Creds(corpId, agentId, corpSecret);
                }
            }
        } catch (Exception e) {
            log.debug("租户级企微凭据解密失败: {}", e.getClass().getSimpleName());
        }
        if (!platformCreds.getCorpId().isBlank() && !platformCreds.getAgentId().isBlank()
                && !platformCreds.getCorpSecret().isBlank()) {
            return new Creds(platformCreds.getCorpId(), platformCreds.getAgentId(),
                    platformCreds.getCorpSecret());
        }
        return null;
    }

    /**
     * 发起授权：校验 returnPath / origin（防开放重定向）→ 生成一次性 state →
     * 返回企业微信网页授权 URL（scope=snsapi_privateinfo）。
     *
     * <p>登录发生在租户上下文之前，凭据统一取**平台级**（tenant 0）配置：
     * 管理端 admin（tenant 0）在「连接器配置」保存的即是这一份。</p>
     */
    public String start(String returnPath, String origin, String host) {
        if (returnPath == null || !returnPath.startsWith("/") || returnPath.contains("//")
                || returnPath.contains("\\")) {
            throw BizException.badRequest("returnPath 非法（须为同站相对路径）");
        }
        if (origin == null || origin.isBlank()) {
            throw BizException.badRequest("缺少 Origin，拒绝授权跳转");
        }
        String originHost = hostOf(origin);
        String reqHost = hostOfHeader(host);
        if (originHost == null || reqHost == null || !originHost.equalsIgnoreCase(reqHost)) {
            throw BizException.badRequest("Origin 与 Host 主机名不一致，拒绝开放重定向");
        }
        Creds creds = creds(PLATFORM_TENANT_ID);
        if (creds == null) {
            throw BizException.badRequest("企业微信登录未配置：请管理员在「连接器配置」填写 corpId / agentId / corpSecret");
        }

        String state = UUID.randomUUID().toString().replace("-", "");
        WeComLoginPending p = new WeComLoginPending();
        p.setState(state);
        p.setTenantId(PLATFORM_TENANT_ID);
        p.setOrigin(origin);
        p.setReturnPath(returnPath);
        p.setCreatedAt(LocalDateTime.now());
        pendingMapper.insert(p);

        String callbackBase = callbackBase(origin);
        String callbackUrl = callbackBase.replaceAll("/+$", "") + "/api/v1/auth/wecom/callback";
        return WEB_AUTH_BASE
                + "?appid=" + enc(creds.corpId())
                + "&redirect_uri=" + enc(callbackUrl)
                + "&response_type=code"
                + "&scope=snsapi_privateinfo"
                + "&state=" + enc(state)
                + "&agentid=" + enc(creds.agentId())
                + "#wechat_redirect";
    }

    /**
     * 授权回调：校验 state → code 换身份 → 命中绑定直接签发本地令牌（返回 302 目标）；
     * 未命中返回「引导绑定」目标（带 wecom_bind=&lt;state&gt;）。
     *
     * @return 302 Location（hash 携带令牌，避免进服务器访问日志）
     */
    public String callback(String code, String state, String ip, String ua) {
        WeComLoginPending p = pendingMapper.selectById(state);
        if (p == null) {
            // 伪造 state：无可信 origin，只回 H5 首页失败态
            return "/aios/h5/?wecom_login=fail&reason=invalid_state";
        }
        if (p.getUsedAt() != null) {
            return redirect(p, "fail", "state 已使用");
        }
        if (p.getCreatedAt() == null
                || Duration.between(p.getCreatedAt(), LocalDateTime.now()).compareTo(STATE_TTL) > 0) {
            return redirect(p, "fail", "state 已过期");
        }
        // 一次性：立即作废（失败也作废，防 code 重放试探）
        pendingMapper.update(null, new LambdaUpdateWrapper<WeComLoginPending>()
                .eq(WeComLoginPending::getState, state)
                .set(WeComLoginPending::getUsedAt, LocalDateTime.now()));

        Creds creds = creds(p.getTenantId());
        if (creds == null) {
            return redirect(p, "fail", "企业微信登录未配置");
        }
        String accessToken;
        try {
            accessToken = weComAuth.getToken(creds.corpId(), creds.corpSecret()).accessToken();
        } catch (Exception e) {
            log.info("wecom login gettoken 失败: {}", e.getMessage());
            return redirect(p, "fail", "获取 access_token 失败");
        }
        WeComAuthClient.UserInfo info;
        try {
            info = weComAuth.getUserInfo(accessToken, code);
        } catch (Exception e) {
            log.info("wecom login getuserinfo 失败: {}", e.getMessage());
            return redirect(p, "fail", "授权信息获取失败");
        }
        if (info.userid() == null || info.userid().isBlank()) {
            return redirect(p, "fail", "未获取到企业微信 userid");
        }
        String userid = info.userid();
        String bizMail = null;
        String name = null;
        if (info.userTicket() != null && !info.userTicket().isBlank()) {
            try {
                WeComAuthClient.UserDetail d = weComAuth.getUserDetail(accessToken, info.userTicket());
                bizMail = d.bizMail();
                name = d.name();
            } catch (Exception e) {
                // getuserdetail 失败不阻断登录：userid 已到手，只是绑定缺邮箱参考
                log.info("wecom login getuserdetail 未成功（不阻断）: {}", e.getMessage());
            }
        }

        WeComLoginBinding binding = bindingMapper.selectOne(new LambdaQueryWrapper<WeComLoginBinding>()
                .eq(WeComLoginBinding::getTenantId, p.getTenantId())
                .eq(WeComLoginBinding::getWecomUserid, userid));
        if (binding == null) {
            // 未绑定：身份暂存 pending，引导本地登录后 bind
            pendingMapper.update(null, new LambdaUpdateWrapper<WeComLoginPending>()
                    .eq(WeComLoginPending::getState, state)
                    .set(WeComLoginPending::getWecomUserid, userid)
                    .set(WeComLoginPending::getBizMail, bizMail)
                    .set(WeComLoginPending::getName, name));
            return redirect(p, "bind", null);
        }
        // 已绑定：直接签发本地令牌，经 hash 回 H5
        try {
            AuthService.LoginData data = authService.issueForExternalUser(binding.getUserId(), ip, ua);
            return redirect(p, "ok", null)
                    + "#wecom_token=" + enc(data.accessToken())
                    + "&wecom_refresh=" + enc(data.refreshToken());
        } catch (BizException e) {
            return redirect(p, "fail", e.getMessage());
        }
    }

    /** H5 展示「检测到企业微信身份 XXX」用（state 即能力凭证，一次性）。 */
    public Map<String, Object> pendingStatus(String state) {
        WeComLoginPending p = state == null ? null : pendingMapper.selectById(state);
        if (p == null || p.getUsedAt() == null || p.getWecomUserid() == null) {
            throw BizException.badRequest("授权已过期，请重新发起企业微信登录");
        }
        return Map.of("wecomUserid", p.getWecomUserid(),
                "bizMail", p.getBizMail() == null ? "" : p.getBizMail(),
                "name", p.getName() == null ? "" : p.getName());
    }

    /** 本地登录成功后调用：把 pending 里的企微身份绑到当前账号。幂等（已绑定直接成功）。 */
    public Map<String, Object> bind(String state, AuthUser user) {
        WeComLoginPending p = pendingMapper.selectById(state);
        if (p == null || p.getUsedAt() == null || p.getWecomUserid() == null) {
            throw BizException.badRequest("授权已过期，请重新发起企业微信登录");
        }
        WeComLoginBinding exist = bindingMapper.selectOne(new LambdaQueryWrapper<WeComLoginBinding>()
                .eq(WeComLoginBinding::getTenantId, p.getTenantId())
                .eq(WeComLoginBinding::getWecomUserid, p.getWecomUserid()));
        if (exist != null) {
            if (!exist.getUserId().equals(user.getUserId())) {
                throw BizException.badRequest("该企业微信身份已绑定其他账号");
            }
            return Map.of("bound", true, "userId", user.getUserId());
        }
        LocalDateTime now = LocalDateTime.now();
        WeComLoginBinding b = new WeComLoginBinding();
        b.setTenantId(p.getTenantId());
        b.setWecomUserid(p.getWecomUserid());
        b.setBizMail(p.getBizMail());
        b.setName(p.getName());
        b.setUserId(user.getUserId());
        b.setCreatedAt(now);
        b.setUpdatedAt(now);
        bindingMapper.insert(b);
        log.info("企微登录绑定建立 wecomUserid={} userId={}", p.getWecomUserid(), user.getUserId());
        return Map.of("bound", true, "userId", user.getUserId());
    }

    // ---------- 内部 ----------

    private String redirect(WeComLoginPending p, String result, String message) {
        String origin = p.getOrigin() == null ? "" : p.getOrigin();
        String returnPath = p.getReturnPath() == null ? "/" : p.getReturnPath();
        StringBuilder sb = new StringBuilder(origin).append(returnPath);
        sb.append(sb.indexOf("?") >= 0 ? "&" : "?");
        sb.append("wecom_login=").append(result);
        if (message != null) {
            sb.append("&reason=").append(enc(message));
        }
        return sb.toString();
    }

    private String callbackBase(String origin) {
        if (props.getPublicBase() != null && !props.getPublicBase().isBlank()) {
            return props.getPublicBase();
        }
        return origin;
    }

    private String secretCodecDecrypt(String secretJson) {
        return secretCodec.decrypt(secretJson);
    }

    private static String enc(String s) {
        return URLEncoder.encode(s == null ? "" : s, StandardCharsets.UTF_8);
    }

    private static String hostOf(String url) {
        try {
            return new java.net.URI(url).getHost();
        } catch (Exception e) {
            return null;
        }
    }

    private static String hostOfHeader(String host) {
        if (host == null) {
            return null;
        }
        int idx = host.indexOf(':');
        return idx >= 0 ? host.substring(0, idx) : host;
    }
}
