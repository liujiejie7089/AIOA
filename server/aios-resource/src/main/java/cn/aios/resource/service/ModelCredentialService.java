package cn.aios.resource.service;

import cn.aios.common.crypto.SecretCodec;
import cn.aios.common.exception.BizException;
import cn.aios.resource.entity.CredentialShare;
import cn.aios.resource.entity.ModelCredential;
import cn.aios.resource.mapper.CredentialShareMapper;
import cn.aios.resource.mapper.ModelCredentialMapper;
import cn.aios.security.AuthUser;
import cn.aios.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

/**
 * 模型账号（凭证）与共享授权。
 *
 * <p>三条主链路：</p>
 * <ol>
 *   <li><b>建账号</b>：用户录入自己在供应商注册的 Key，或由租户管理员建公司账号。
 *       Key 落库前用 {@link SecretCodec} 加密，出参只给掩码。</li>
 *   <li><b>邀请共享</b>：持有人把账号授权给同租户同事，被邀请人消耗的词元
 *       <b>记在持有人头上</b>（{@code charge_user_id = ownerUserId}），
 *      持有人自己的额度一点不扣 —— 这就是「由邀请者承担」在数据上的全部含义。</li>
 *   <li><b>解析可用账号</b>：一轮对话开跑前，决定这一轮到底用谁的凭证。</li>
 * </ol>
 *
 * <p><b>为什么「是否公司收费」由本服务推导而不接受传参</b>：
 * 前端能传这个字段，就能把账单口径改成任何值。规则只有一条 ——
 * {@code company_charged = (owner_type == COMPANY)}，在 {@link ModelCredential#companyCharged()}
 * 与 {@link BillingService#companyChargedOf(String)} 各推导一次，两处同源。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ModelCredentialService {

    /** 单人共享人数上限：挡住「把我的 Key 发给全公司」这类滥用。 */
    private static final int MAX_GRANTEES = 20;

    private final ModelCredentialMapper credentialMapper;
    private final CredentialShareMapper shareMapper;
    private final SecretCodec secretCodec;
    private final JdbcTemplate jdbc;

    /**
     * 一次账号在调用方的形态：**明文 Key 只在这里出现，绝不出现在任何接口回执里**。
     *
     * <p>2026-11-04：额外携带 9 个采样/传输参数（与平台 model_config 同名同义），
     * 未填的项为 null，agent 侧按「用户配置 &gt; 平台配置 &gt; 内置默认」回落。</p>
     */
    public record Resolved(Long credentialId, String providerKey, String baseUrl, String model,
                           String apiKey, Long chargeUserId, String ownerType,
                           java.math.BigDecimal temperature, java.math.BigDecimal topP,
                           Integer maxTokens, Integer maxContext,
                           java.math.BigDecimal presencePenalty, java.math.BigDecimal frequencyPenalty,
                           Integer timeoutSeconds, Integer retryAttempts, Boolean streamEnabled) {

        public boolean companyCharged() {
            return ModelCredential.OWNER_COMPANY.equalsIgnoreCase(ownerType);
        }
    }

    /** 列表/详情形态：不含密钥，只带掩码。 */
    public record CredentialView(Long id, String ownerType, Long ownerUserId, String providerKey,
                                 String providerType, String name, String baseUrl, String modelName,
                                 String keyHint, boolean shareEnabled, boolean enabled, String remark,
                                 int shareCount, LocalDateTime createdAt,
                                 java.math.BigDecimal temperature, java.math.BigDecimal topP,
                                 Integer maxTokens, Integer maxContext,
                                 java.math.BigDecimal presencePenalty, java.math.BigDecimal frequencyPenalty,
                                 Integer timeoutSeconds, Integer retryAttempts, Boolean streamEnabled) {

        static CredentialView from(ModelCredential c, int shareCount) {
            return new CredentialView(c.getId(), c.getOwnerType(), c.getOwnerUserId(), c.getProviderKey(),
                    c.getProviderType(), c.getName(), c.getBaseUrl(), c.getModelName(), c.getKeyHint(),
                    c.shareAllowed(), c.isEnabled(), c.getRemark(), shareCount, c.getCreatedAt(),
                    c.getTemperature(), c.getTopP(), c.getMaxTokens(), c.getMaxContext(),
                    c.getPresencePenalty(), c.getFrequencyPenalty(),
                    c.getTimeoutSeconds(), c.getRetryAttempts(), c.getStreamEnabled());
        }
    }

    /** 共享关系形态（「我邀请的」与「邀请我的」共用）。 */
    public record ShareView(Long id, Long credentialId, String credentialName, String providerKey,
                            Long ownerUserId, String ownerName, Long granteeUserId, String granteeName,
                            String status, Long quotaTokens, Long usedTokens,
                            LocalDateTime expiresAt, LocalDateTime createdAt, boolean exhausted) {

        static ShareView from(CredentialShare s, String credentialName, String providerKey,
                              String ownerName, LocalDateTime now) {
            return new ShareView(s.getId(), s.getCredentialId(), credentialName, providerKey,
                    s.getOwnerUserId(), ownerName, s.getGranteeUserId(), s.getGranteeName(),
                    s.getStatus(), s.getQuotaTokens(), s.getUsedTokens(), s.getExpiresAt(),
                    s.getCreatedAt(), s.exhausted());
        }
    }

    // ---------- 建 / 改 / 删 / 查 ----------

    /**
     * 我的账号列表：自己持有的 + 公司账号 + 邀请给我的。
     * 三者分开返回，前端按 tab 展示，避免「把公司的 Key 当成我的」。
     */
    public Map<String, Object> myAccounts(AuthUser user) {
        Long tenantId = tenantOf(user);
        long uid = user.getUserId();
        List<ModelCredential> mine = credentialMapper.selectList(new LambdaQueryWrapper<ModelCredential>()
                .eq(ModelCredential::getTenantId, tenantId)
                .eq(ModelCredential::getOwnerUserId, uid)
                .orderByDesc(ModelCredential::getId));
        List<ModelCredential> company = credentialMapper.selectList(new LambdaQueryWrapper<ModelCredential>()
                .eq(ModelCredential::getTenantId, tenantId)
                .eq(ModelCredential::getOwnerType, ModelCredential.OWNER_COMPANY)
                .orderByDesc(ModelCredential::getId));

        List<ModelCredential> shared = new ArrayList<>();
        List<CredentialShare> grants = shareMapper.selectList(new LambdaQueryWrapper<CredentialShare>()
                .eq(CredentialShare::getTenantId, tenantId)
                .eq(CredentialShare::getGranteeUserId, uid)
                .orderByDesc(CredentialShare::getId));
        for (CredentialShare s : grants) {
            if (!s.usable(now())) {
                markExpiredIfNeeded(s);
                continue;
            }
            ModelCredential c = credentialMapper.selectById(s.getCredentialId());
            if (c != null && c.isEnabled()) {
                shared.add(c);
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("mine", mine.stream().map(c -> CredentialView.from(c, countShares(c.getId()))).toList());
        out.put("company", company.stream().map(c -> CredentialView.from(c, countShares(c.getId()))).toList());
        out.put("shared", shared.stream().map(c -> CredentialView.from(c, countShares(c.getId()))).toList());
        return out;
    }

    /** 新建账号。COMPANY 需要租户管理员；PERSONAL 任何人可建，归属写自己。 */
    @Transactional(rollbackFor = Exception.class)
    public CredentialView create(AuthUser user, Map<String, Object> body) {
        Map<String, Object> req = body == null ? Map.of() : body;
        String ownerType = str(req.get("ownerType"), ModelCredential.OWNER_PERSONAL)
                .trim().toUpperCase(Locale.ROOT);
        if (!ModelCredential.OWNER_PERSONAL.equals(ownerType)
                && !ModelCredential.OWNER_COMPANY.equals(ownerType)) {
            throw BizException.badRequest("ownerType 只能是 PERSONAL 或 COMPANY");
        }
        if (ModelCredential.OWNER_COMPANY.equals(ownerType) && !PermissionCatalog.isAdmin(user)) {
            throw BizException.forbidden("公司账号只能由租户管理员创建");
        }
        String providerKey = require(req.get("providerKey"), "providerKey");
        String name = require(req.get("name"), "name");
        String apiKey = require(req.get("apiKey"), "apiKey");

        // 同名检查按「同租户 + 同属主 + 同供应商 + 同名」判。
        // 公司账号的 owner_user_id 是 NULL：既不能用 eq(col, null)（恒假，检查被静默跳过），
        // 也不能指望唯一键——MySQL 唯一索引不约束 NULL，同名的公司账号会被放进去。
        // 软删行由逻辑删除自动排除（唯一键带 deleted_at 本就是为「删后重建同名」留的口）。
        LambdaQueryWrapper<ModelCredential> dupQ = Wrappers.<ModelCredential>lambdaQuery()
                .eq(ModelCredential::getTenantId, tenantOf(user))
                .eq(ModelCredential::getProviderKey, providerKey)
                .eq(ModelCredential::getName, name);
        Long ownerId = ownerUserIdOf(user, ownerType);
        if (ownerId == null) {
            dupQ.isNull(ModelCredential::getOwnerUserId);
        } else {
            dupQ.eq(ModelCredential::getOwnerUserId, ownerId);
        }
        long dup = credentialMapper.selectCount(dupQ);
        if (dup > 0) {
            throw BizException.badRequest("同名账号已存在：" + name);
        }

        ModelCredential c = new ModelCredential();
        c.setTenantId(tenantOf(user));
        c.setOwnerType(ownerType);
        c.setOwnerUserId(ownerUserIdOf(user, ownerType));
        c.setProviderKey(providerKey);
        c.setProviderType(str(req.get("providerType"), "openai_compatible"));
        c.setName(name);
        c.setBaseUrl(blankToNull(str(req.get("baseUrl"), null)));
        c.setModelName(blankToNull(str(req.get("modelName"), null)));
        c.setApiKeyCipher(secretCodec.encrypt(apiKey.trim()));
        c.setKeyHint(mask(apiKey.trim()));
        c.setShareEnabled(bool(req.get("shareEnabled")) ? 1 : 0);
        c.setStatus(ModelCredential.STATUS_ENABLED);
        c.setRemark(blankToNull(str(req.get("remark"), null)));
        applyParams(c, req, false);
        c.setCreatedAt(LocalDateTime.now());
        c.setCreatedBy(user.getUserId());
        credentialMapper.insert(c);
        log.info("model credential created: id={} tenant={} owner={} type={} provider={}",
                c.getId(), c.getTenantId(), c.getOwnerUserId(), c.getOwnerType(), c.getProviderKey());
        return CredentialView.from(c, 0);
    }

    /** 修改。COMPANY 账号的 shareEnabled / status 只允许管理员改（公司资产）。 */
    public CredentialView update(AuthUser user, Long id, Map<String, Object> body) {
        Map<String, Object> req = body == null ? Map.of() : body;
        ModelCredential c = loadOwned(user, id);
        if (req.containsKey("name")) {
            c.setName(require(req.get("name"), "name"));
        }
        if (req.containsKey("baseUrl")) {
            c.setBaseUrl(blankToNull(str(req.get("baseUrl"), null)));
        }
        if (req.containsKey("modelName")) {
            c.setModelName(blankToNull(str(req.get("modelName"), null)));
        }
        if (req.containsKey("remark")) {
            c.setRemark(blankToNull(str(req.get("remark"), null)));
        }
        applyParams(c, req, true);
        if (req.containsKey("apiKey")) {
            String apiKey = str(req.get("apiKey"), "").trim();
            if (apiKey.isEmpty()) {
                throw BizException.badRequest("apiKey 不能为空（不换 Key 时请不要传该字段）")
                        .withDetails(java.util.List.of(
                                new cn.aios.common.error.ErrorText.FieldError("apiKey", "不能为空")));
            }
            c.setApiKeyCipher(secretCodec.encrypt(apiKey));
            c.setKeyHint(mask(apiKey));
        }
        boolean companyKey = c.isCompany();
        if (req.containsKey("shareEnabled")) {
            if (companyKey && !PermissionCatalog.isAdmin(user)) {
                throw BizException.forbidden("公司账号的共享开关只能由管理员修改");
            }
            c.setShareEnabled(bool(req.get("shareEnabled")) ? 1 : 0);
        }
        if (req.containsKey("status")) {
            if (companyKey && !PermissionCatalog.isAdmin(user)) {
                throw BizException.forbidden("公司账号的启停只能由管理员修改");
            }
            String status = str(req.get("status"), ModelCredential.STATUS_ENABLED).trim()
                    .toUpperCase(Locale.ROOT);
            if (!ModelCredential.STATUS_ENABLED.equals(status)
                    && !ModelCredential.STATUS_DISABLED.equals(status)) {
                throw BizException.badRequest("status 只能是 ENABLED 或 DISABLED");
            }
            c.setStatus(status);
        }
        c.setUpdatedAt(LocalDateTime.now());
        c.setUpdatedBy(user.getUserId());
        credentialMapper.updateById(c);
        return CredentialView.from(c, countShares(c.getId()));
    }

    /**
     * 删除（软删）。共享行<b>不级联删</b> —— 那是审计痕迹，删了就查不到
     * 「这个人曾经把 Key 给过谁」。
     */
    public void delete(AuthUser user, Long id) {
        ModelCredential c = loadOwned(user, id);
        credentialMapper.deleteById(c.getId());
        log.info("model credential deleted: id={} by user={}", c.getId(), user.getUserId());
    }

    // ---------- 邀请 / 接受 / 撤销 ----------

    /** 我发起的共享邀请。 */
    public List<ShareView> myInvites(AuthUser user) {
        Long tenantId = tenantOf(user);
        List<CredentialShare> rows = shareMapper.selectList(new LambdaQueryWrapper<CredentialShare>()
                .eq(CredentialShare::getTenantId, tenantId)
                .eq(CredentialShare::getOwnerUserId, user.getUserId())
                .orderByDesc(CredentialShare::getId));
        return decorate(rows);
    }

    /** 邀请给我的共享（含已撤销/已过期的历史）。 */
    public List<ShareView> invitesToMe(AuthUser user) {
        List<CredentialShare> rows = shareMapper.selectList(new LambdaQueryWrapper<CredentialShare>()
                .eq(CredentialShare::getTenantId, tenantOf(user))
                .eq(CredentialShare::getGranteeUserId, user.getUserId())
                .orderByDesc(CredentialShare::getId));
        return decorate(rows);
    }

    /**
     * 邀请同事共用账号。
     *
     * <p>校验清单见 docs/71 §5，逐条对应下面的 throw —— 每条都要有明确文案，
     * 不做静默失败（失败但没提示，用户只会看到「点了没反应」）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public ShareView invite(AuthUser user, Long credentialId, Map<String, Object> body) {
        Map<String, Object> req = body == null ? Map.of() : body;
        ModelCredential c = loadOwned(user, credentialId);
        if (!c.isEnabled()) {
            throw BizException.badRequest("账号已停用，无法共享");
        }
        if (!c.shareAllowed()) {
            throw BizException.badRequest("该账号未开启共享，请先在账号详情里打开「允许共享」");
        }
        if (c.isCompany() && !PermissionCatalog.isAdmin(user)) {
            throw BizException.forbidden("公司账号只能由管理员共享");
        }
        Long granteeId = parseUserId(req.get("granteeUserId"));
        String granteeUsername = str(req.get("granteeUsername"), null);
        Map<String, Object> target = null;
        if (granteeId != null) {
            target = findUser(granteeId, tenantOf(user));
        } else if (granteeUsername != null && !granteeUsername.isBlank()) {
            target = findUserByUsername(granteeUsername.trim(), tenantOf(user));
        }
        if (target == null) {
            throw BizException.badRequest("只能邀请本单位在职同事（按用户名或 userId 指定，且账号为启用状态）");
        }
        long gid = ((Number) target.get("id")).longValue();
        String gname = String.valueOf(target.getOrDefault("nickname", "同事#" + gid));
        if (Objects.equals(gid, user.getUserId())) {
            throw BizException.badRequest("不能邀请自己");
        }

        CredentialShare exists = shareMapper.selectOne(new LambdaQueryWrapper<CredentialShare>()
                .eq(CredentialShare::getCredentialId, c.getId())
                .eq(CredentialShare::getGranteeUserId, gid));
        if (exists != null && CredentialShare.STATUS_ACTIVE.equalsIgnoreCase(exists.getStatus())) {
            throw BizException.badRequest("该同事已在共享名单中，无需重复邀请");
        }

        long count = shareMapper.selectCount(Wrappers.<CredentialShare>lambdaQuery()
                .eq(CredentialShare::getCredentialId, c.getId())
                .eq(CredentialShare::getStatus, CredentialShare.STATUS_ACTIVE));
        if (count >= MAX_GRANTEES) {
            throw BizException.badRequest("共享人数已达上限（" + MAX_GRANTEES + " 人）");
        }

        // 撤销后再次邀请复用同一行：唯一键会挡住插入，且复用行保留了「曾撤销过」的时间线。
        // usedTokens 一律重置 —— 否则上轮的用量会直接顶掉新配额，被邀请人还没用就被判超额。
        CredentialShare s = exists != null ? exists : new CredentialShare();
        s.setTenantId(tenantOf(user));
        s.setCredentialId(c.getId());
        s.setOwnerUserId(c.getOwnerUserId());
        s.setGranteeUserId(gid);
        s.setGranteeName(gname);
        s.setStatus(CredentialShare.STATUS_ACTIVE);
        s.setInviteCode(newInviteCode());
        long quota = nonNegative(req.get("quotaTokens"));
        s.setQuotaTokens(quota);
        s.setUsedTokens(0L);
        s.setExpiresAt(parseDate(req.get("expiresAt")));
        s.setAcceptedAt(LocalDateTime.now());
        s.setRevokedAt(null);
        if (exists != null) {
            s.setUpdatedAt(LocalDateTime.now());
            shareMapper.updateById(s);
        } else {
            s.setCreatedAt(LocalDateTime.now());
            s.setCreatedBy(user.getUserId());
            shareMapper.insert(s);
        }
        log.info("credential share granted: credential={} owner={} grantee={} quota={} expires={}",
                c.getId(), c.getOwnerUserId(), gid, quota, s.getExpiresAt());
        return decorateOne(s);
    }

    /** 接受邀请（按邀请码）。邀请时已直接置 ACTIVE，本方法给未来的「待确认」流程留口。 */
    public ShareView accept(AuthUser user, Long shareId, String inviteCode) {
        CredentialShare s = shareMapper.selectById(shareId);
        if (s == null) {
            throw BizException.notFound("共享邀请不存在");
        }
        if (!Objects.equals(s.getGranteeUserId(), user.getUserId())) {
            throw BizException.forbidden("该共享不是邀请给你的");
        }
        if (s.getInviteCode() != null && !s.getInviteCode().equalsIgnoreCase(str(inviteCode, ""))) {
            throw BizException.badRequest("邀请码不正确");
        }
        if (CredentialShare.STATUS_ACTIVE.equalsIgnoreCase(s.getStatus())) {
            return decorateOne(s);
        }
        s.setStatus(CredentialShare.STATUS_ACTIVE);
        s.setAcceptedAt(LocalDateTime.now());
        s.setRevokedAt(null);
        s.setUpdatedAt(LocalDateTime.now());
        shareMapper.updateById(s);
        return decorateOne(s);
    }

    /**
     * 撤销共享。撤销后<b>不打断</b>已在跑的 run（启动时已快照归属），
     * 下一轮解析不到 ⇒ 回落平台默认通道。
     */
    @Transactional(rollbackFor = Exception.class)
    public void revoke(AuthUser user, Long shareId) {
        CredentialShare s = shareMapper.selectById(shareId);
        if (s == null) {
            throw BizException.notFound("共享关系不存在");
        }
        boolean isOwner = Objects.equals(s.getOwnerUserId(), user.getUserId());
        if (!isOwner) {
            // 公司账号：管理员可代持撤销；个人账号只允许持有人撤销
            ModelCredential c = credentialMapper.selectById(s.getCredentialId());
            boolean adminOfCompany = c != null && c.isCompany() && PermissionCatalog.isAdmin(user);
            if (!adminOfCompany && !Objects.equals(s.getGranteeUserId(), user.getUserId())) {
                throw BizException.forbidden("只有邀请人或被邀请人可以撤销该共享");
            }
        }
        s.setStatus(CredentialShare.STATUS_REVOKED);
        s.setRevokedAt(LocalDateTime.now());
        s.setUpdatedAt(LocalDateTime.now());
        shareMapper.updateById(s);
        log.info("credential share revoked: id={} by user={}", s.getId(), user.getUserId());
    }

    /** 被邀请人主动退出（等价撤销，语义上写「退出共享」）。 */
    public void leave(AuthUser user, Long shareId) {
        CredentialShare s = shareMapper.selectById(shareId);
        if (s == null || !Objects.equals(s.getGranteeUserId(), user.getUserId())) {
            throw BizException.notFound("共享关系不存在");
        }
        s.setStatus(CredentialShare.STATUS_REVOKED);
        s.setRevokedAt(LocalDateTime.now());
        s.setUpdatedAt(LocalDateTime.now());
        shareMapper.updateById(s);
    }

    // ---------- 运行期解析 ----------

    /**
     * 解析「当前用户这一轮能不能用这个账号」。
     *
     * <p>显式指定却不可用 ⇒ <b>抛异常，不静默降级</b>：悄悄换成别人的 Key 跑，
     * 账单上会挂到完全不相干的人头上，这比报错更糟。只有「没指定」时才走自动顺序
     * （见 {@link #autoResolve}）。</p>
     */
    public Resolved resolve(AuthUser user, Long credentialId) {
        if (credentialId == null || credentialId <= 0) {
            throw BizException.badRequest("credentialId 非法");
        }
        return loadForUser(user, credentialId, true);
    }

    /**
     * 自动选账号：自己的 → 公司账号 → 无（走平台默认通道）。
     *
     * <p>顺序即优先级：<b>用户自己的 Key 优先</b>（他可能希望用自己充值的额度），
     * 公司账号兜底（保证没注册 Key 的人也能用）。</p>
     */
    public Resolved autoResolve(AuthUser user) {
        try {
            List<ModelCredential> mine = credentialMapper.selectList(new LambdaQueryWrapper<ModelCredential>()
                    .eq(ModelCredential::getTenantId, tenantOf(user))
                    .eq(ModelCredential::getOwnerUserId, user.getUserId())
                    .eq(ModelCredential::getStatus, ModelCredential.STATUS_ENABLED)
                    .orderByDesc(ModelCredential::getId));
            if (!mine.isEmpty()) {
                return fromEntity(mine.get(0));
            }
            List<ModelCredential> company = credentialMapper.selectList(new LambdaQueryWrapper<ModelCredential>()
                    .eq(ModelCredential::getTenantId, tenantOf(user))
                    .eq(ModelCredential::getOwnerType, ModelCredential.OWNER_COMPANY)
                    .eq(ModelCredential::getStatus, ModelCredential.STATUS_ENABLED)
                    .orderByAsc(ModelCredential::getId));
            if (!company.isEmpty()) {
                return fromEntity(company.get(0));
            }
        } catch (Exception e) {
            // 账号解析失败绝不能把对话打死：回落平台默认通道，日志留痕。
            log.warn("auto resolve credential failed for user {}: {}", user.getUserId(), e.getMessage());
        }
        return null;
    }

    /** 明文 Key 只在本服务内出现；这里给 agent 下发用。 */
    public String plainKey(ModelCredential c) {
        return secretCodec.decrypt(c.getApiKeyCipher());
    }

    // ---------- 内部 ----------

    /** 载入并对使用者做权限判定：本人持有 / ACTIVE 共享 / 公司账号（本租户）。 */
    private Resolved loadForUser(AuthUser user, Long credentialId, boolean strict) {
        ModelCredential c = credentialMapper.selectById(credentialId);
        if (c == null || !Objects.equals(c.getTenantId(), tenantOf(user))) {
            throw BizException.notFound("账号不存在");
        }
        if (!c.isEnabled()) {
            throw BizException.badRequest("账号已停用，无法使用");
        }
        Long uid = user.getUserId();
        boolean mine = Objects.equals(c.getOwnerUserId(), uid);
        if (mine) {
            return fromEntity(c);
        }
        if (c.isCompany()) {
            // 公司账号：本租户任何在职员工都可用（公司资产），扣公司池
            return fromEntity(c);
        }
        CredentialShare s = shareMapper.selectOne(new LambdaQueryWrapper<CredentialShare>()
                .eq(CredentialShare::getCredentialId, c.getId())
                .eq(CredentialShare::getGranteeUserId, uid));
        if (s == null || !s.usable(now())) {
            if (s != null) {
                markExpiredIfNeeded(s);
            }
            throw BizException.forbidden("该账号未共享给你（或共享已被撤销/已过期）");
        }
        if (s.exhausted()) {
            throw BizException.forbidden("该共享额度已用尽，请联系账号持有人");
        }
        return fromEntity(c);
    }

    private Resolved fromEntity(ModelCredential c) {
        return new Resolved(c.getId(), c.getProviderKey(), c.getBaseUrl(), c.getModelName(),
                plainKey(c), c.chargeUserId(), c.getOwnerType(),
                c.getTemperature(), c.getTopP(), c.getMaxTokens(), c.getMaxContext(),
                c.getPresencePenalty(), c.getFrequencyPenalty(),
                c.getTimeoutSeconds(), c.getRetryAttempts(), c.getStreamEnabled());
    }

    /** 本人 / 公司管理员 才能操作；他人账号一律 404（不泄露存在性）。 */
    private ModelCredential loadOwned(AuthUser user, Long id) {
        if (id == null) {
            throw BizException.badRequest("id 不能为空");
        }
        ModelCredential c = credentialMapper.selectById(id);
        if (c == null || !Objects.equals(c.getTenantId(), tenantOf(user))) {
            throw BizException.notFound("账号不存在");
        }
        if (!Objects.equals(c.getOwnerUserId(), user.getUserId())
                && !(c.isCompany() && PermissionCatalog.isAdmin(user))) {
            throw BizException.notFound("账号不存在");
        }
        return c;
    }

    /**
     * 采样/传输参数（2026-11-04，docs/72 §2）。
     *
     * <p>范围与平台侧 {@code ModelConfigController.validate}、agent 侧 {@code PARAM_RANGES}
     * 三处同源；partial=true 时只更新请求里出现的键（PUT 语义）。</p>
     */
    private void applyParams(ModelCredential c, Map<String, Object> req, boolean partial) {
        if (!partial || req.containsKey("temperature")) {
            c.setTemperature(decParam(req.get("temperature"), "温度", 0, 2, new java.math.BigDecimal("0.30")));
        }
        if (!partial || req.containsKey("topP")) {
            c.setTopP(decParam(req.get("topP"), "top_p", 0, 1, null));
        }
        if (!partial || req.containsKey("maxTokens")) {
            c.setMaxTokens(intParam(req.get("maxTokens"), "单次输出上限", 0, 65536, 0));
        }
        if (!partial || req.containsKey("maxContext")) {
            c.setMaxContext(intParam(req.get("maxContext"), "上下文长度", 0, 1048576, 0));
        }
        if (!partial || req.containsKey("presencePenalty")) {
            c.setPresencePenalty(decParam(req.get("presencePenalty"), "话题新颖度惩罚",
                    -2, 2, java.math.BigDecimal.ZERO));
        }
        if (!partial || req.containsKey("frequencyPenalty")) {
            c.setFrequencyPenalty(decParam(req.get("frequencyPenalty"), "词频惩罚",
                    -2, 2, java.math.BigDecimal.ZERO));
        }
        if (!partial || req.containsKey("timeoutSeconds")) {
            c.setTimeoutSeconds(intParam(req.get("timeoutSeconds"), "请求超时", 5, 600, 120));
        }
        if (!partial || req.containsKey("retryAttempts")) {
            c.setRetryAttempts(intParam(req.get("retryAttempts"), "重试次数", 1, 5, 3));
        }
        if (!partial || req.containsKey("streamEnabled")) {
            c.setStreamEnabled(req.containsKey("streamEnabled") ? bool(req.get("streamEnabled")) : Boolean.TRUE);
        }
    }

    private static java.math.BigDecimal decParam(Object raw, String label, double lo, double hi,
                                                 java.math.BigDecimal dft) {
        if (raw == null || String.valueOf(raw).isBlank()) {
            return dft;
        }
        java.math.BigDecimal v;
        try {
            v = new java.math.BigDecimal(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            throw BizException.badRequest(label + " 不是有效数字");
        }
        if (v.compareTo(java.math.BigDecimal.valueOf(lo)) < 0
                || v.compareTo(java.math.BigDecimal.valueOf(hi)) > 0) {
            throw BizException.badRequest(label + " 需介于 " + (int) lo + " 与 " + (int) hi + " 之间");
        }
        // top_p = 0 与「不填」同义：不下发，避免网关把 0 当非法参数
        if ("top_p".equals(label) && v.compareTo(java.math.BigDecimal.ZERO) == 0) {
            return null;
        }
        return v;
    }

    private static Integer intParam(Object raw, String label, int lo, int hi, int dft) {
        if (raw == null || String.valueOf(raw).isBlank()) {
            return dft;
        }
        int v;
        try {
            v = (int) Double.parseDouble(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            throw BizException.badRequest(label + " 不是有效数字");
        }
        if (v < lo || v > hi) {
            throw BizException.badRequest(label + " 需介于 " + lo + " 与 " + hi + " 之间");
        }
        return v;
    }

    private int countShares(Long credentialId) {        Long n = shareMapper.selectCount(Wrappers.<CredentialShare>lambdaQuery()
                .eq(CredentialShare::getCredentialId, credentialId)
                .eq(CredentialShare::getStatus, CredentialShare.STATUS_ACTIVE));
        return n == null ? 0 : n.intValue();
    }

    private List<ShareView> decorate(List<CredentialShare> rows) {
        LocalDateTime now = now();
        List<ShareView> out = new ArrayList<>(rows.size());
        for (CredentialShare s : rows) {
            out.add(decorateOne(s, now));
        }
        return out;
    }

    private ShareView decorateOne(CredentialShare s) {
        return decorateOne(s, now());
    }

    private ShareView decorateOne(CredentialShare s, LocalDateTime now) {
        // 到期回写：读时判定 + 顺手落库，避免状态永远停在 ACTIVE
        if (!s.usable(now) && CredentialShare.STATUS_ACTIVE.equalsIgnoreCase(s.getStatus())) {
            markExpiredIfNeeded(s);
        }
        ModelCredential c = credentialMapper.selectById(s.getCredentialId());
        String ownerName = c == null ? "" : userName(c.getOwnerUserId());
        return ShareView.from(s, c == null ? "（账号已删除）" : c.getName(),
                c == null ? null : c.getProviderKey(), ownerName, now);
    }

    /** 到期即回写 EXPIRED：读时判定 + 顺手落库，避免状态永远停在 ACTIVE。 */
    private void markExpiredIfNeeded(CredentialShare s) {
        if (!CredentialShare.STATUS_ACTIVE.equalsIgnoreCase(s.getStatus())) {
            return;
        }
        if (s.getExpiresAt() != null && s.getExpiresAt().isBefore(now())) {
            s.setStatus(CredentialShare.STATUS_EXPIRED);
            s.setUpdatedAt(LocalDateTime.now());
            shareMapper.updateById(s);
        }
    }

    private Map<String, Object> findUser(Long id, Long tenantId) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, username, nickname FROM sys_user WHERE id = ? AND tenant_id = ? "
                        + "AND status = 'ENABLED' AND deleted_at IS NULL", id, tenantId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private Map<String, Object> findUserByUsername(String username, Long tenantId) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, username, nickname FROM sys_user WHERE username = ? AND tenant_id = ? "
                        + "AND status = 'ENABLED' AND deleted_at IS NULL", username, tenantId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    /**
     * 可邀请的同事（邀请表单下拉用）：同租户、启用、未删除，排除自己。
     *
     * <p>只回 {@code id / username / nickname} 三个字段 —— 邀请只需要能唯一定位到人，
     * 手机号、邮箱这类信息不带到这个接口上（它与邀请无关，多带就是多一个泄露面）。
     * 上限 200 条：这是「选一个同事」，不是通讯录分页浏览。</p>
     */
    public List<Map<String, Object>> invitable(AuthUser user) {
        return jdbc.queryForList(
                "SELECT id, username, nickname FROM sys_user "
                        + "WHERE tenant_id = ? AND id <> ? AND status = 'ENABLED' AND deleted_at IS NULL "
                        + "ORDER BY nickname, id LIMIT 200",
                tenantOf(user), user.getUserId());
    }

    private String userName(Long userId) {
        if (userId == null) {
            return "";
        }
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT nickname FROM sys_user WHERE id = ?", userId);
        if (rows.isEmpty()) {
            return "用户#" + userId;
        }
        Object nick = rows.get(0).get("nickname");
        return nick == null || String.valueOf(nick).isBlank() ? "用户#" + userId : String.valueOf(nick);
    }

    private static Long ownerUserIdOf(AuthUser user, String ownerType) {
        return ModelCredential.OWNER_COMPANY.equals(ownerType) ? null : user.getUserId();
    }

    private static Long tenantOf(AuthUser user) {
        return user.getTenantId() == null ? 0L : user.getTenantId();
    }

    private static LocalDateTime now() {
        return LocalDateTime.now();
    }

    private static Long parseUserId(Object o) {
        if (o == null || (o instanceof String s && s.isBlank())) {
            return null;
        }
        try {
            return Long.valueOf(String.valueOf(o).trim());
        } catch (RuntimeException e) {
            throw BizException.badRequest("granteeUserId 非法：" + o);
        }
    }

    private static LocalDateTime parseDate(Object o) {
        if (o == null || (o instanceof String s && s.isBlank())) {
            return null;
        }
        try {
            return LocalDateTime.parse(String.valueOf(o).trim());
        } catch (RuntimeException e) {
            throw BizException.badRequest("expiresAt 非法（应为 yyyy-MM-ddTHH:mm:ss）：" + o);
        }
    }

    private static long nonNegative(Object o) {
        if (o == null || (o instanceof String s && s.isBlank())) {
            return 0L;
        }
        try {
            long v = Long.parseLong(String.valueOf(o).trim());
            return Math.max(0L, v);
        } catch (RuntimeException e) {
            throw BizException.badRequest("quotaTokens 非法：" + o);
        }
    }

    private static String require(Object o, String field) {
        String v = o == null ? null : String.valueOf(o).trim();
        if (v == null || v.isEmpty()) {
            // 附上字段级错误：前端据此把对应输入框标红（docs/73 §2.2）。
            // 只给一句「xxx 不能为空」时，用户知道错了但不知道是哪个框。
            throw BizException.badRequest(field + " 不能为空")
                    .withDetails(java.util.List.of(new cn.aios.common.error.ErrorText.FieldError(field, "不能为空")));
        }
        return v;
    }

    private static String str(Object o, String dft) {
        if (o == null) {
            return dft;
        }
        String v = String.valueOf(o).trim();
        return v.isEmpty() ? dft : v;
    }

    private static String blankToNull(String v) {
        return v == null || v.isBlank() ? null : v;
    }

    private static boolean bool(Object o) {
        if (o == null) {
            return false;
        }
        if (o instanceof Boolean b) {
            return b;
        }
        return "1".equals(String.valueOf(o).trim()) || "true".equalsIgnoreCase(String.valueOf(o).trim());
    }

    /** 掩码：只留前 3 后 4，足够用户辨认是哪把 Key，又不足以还原。 */
    static String mask(String apiKey) {
        if (apiKey == null || apiKey.length() <= 8) {
            return "****";
        }
        return apiKey.substring(0, 3) + "****" + apiKey.substring(apiKey.length() - 4);
    }

    private static final String CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

    private static String newInviteCode() {
        byte[] buf = new byte[10];
        new SecureRandom().nextBytes(buf);
        StringBuilder sb = new StringBuilder(10);
        for (byte b : buf) {
            sb.append(CODE_CHARS.charAt(Math.floorMod(b, CODE_CHARS.length())));
        }
        return sb.toString();
    }
}
