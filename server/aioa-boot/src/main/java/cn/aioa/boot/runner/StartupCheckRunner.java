package cn.aioa.boot.runner;

import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.mapper.SysUserMapper;
import cn.aioa.common.security.DevSecretPlaceholders;
import cn.aioa.common.security.SecretStrengthValidator;
import cn.aioa.common.security.SecretStrengthValidator.NamedSecret;
import cn.aioa.gitee.config.GiteaProperties;
import cn.aioa.gitee.config.GiteeProperties;
import cn.aioa.security.JwtProperties;
import cn.aioa.security.ServiceJwtProperties;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 启动自检：校验种子用户 admin 的密码哈希与 "Admin@123" 一致（便于确认 Flyway 种子数据可用），
 * 并对弱密钥 / 占位密钥做 fail-closed（C-1，仅 {@code prod} profile 拒绝启动）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class StartupCheckRunner implements ApplicationRunner {

    private static final String SEED_USERNAME = "admin";
    private static final String SEED_PASSWORD = "Admin@123";

    private final SysUserMapper sysUserMapper;
    private final PasswordEncoder passwordEncoder;
    private final Environment environment;
    private final JwtProperties jwtProperties;
    private final ServiceJwtProperties serviceJwtProperties;
    private final GiteeProperties giteeProperties;
    private final GiteaProperties giteaProperties;

    @Override
    public void run(ApplicationArguments args) {
        checkSecrets();
        checkSeed();
    }

    /**
     * 密钥强度自检（C-1）。
     *
     * <p><b>门控</b>：只有显式 {@code prod} profile 才以异常拒绝启动；其它 profile
     * （本仓默认回退为 {@code dev}，以及 local/test/default）一律只打 WARN —— 本地开发
     * 通常未注入 {@code .env} 环境变量，若在 default 上也 fail-closed 会把本地后端打挂。</p>
     */
    private void checkSecrets() {
        List<NamedSecret> secrets = new ArrayList<>();
        secrets.add(new NamedSecret("aioa.jwt.secret", jwtProperties.getSecret()));
        secrets.add(new NamedSecret("aioa.service-jwt.secret", serviceJwtProperties.getSecret()));
        secrets.add(new NamedSecret("aioa.gitee.token-enc-key", giteeProperties.getTokenEncKey()));
        secrets.add(new NamedSecret("aioa.gitea.token-enc-key", giteaProperties.getTokenEncKey()));

        List<String> violations = new ArrayList<>(SecretStrengthValidator.validate(secrets));

        // 模型 API Key 落库加密：若四个环境变量候选全空，则使用内置弱 fallback 密钥
        boolean modelKeyConfigured = DevSecretPlaceholders.MODEL_KEY_ENV_CANDIDATES.stream()
                .anyMatch(k -> {
                    String v = environment.getProperty(k);
                    return v != null && !v.isBlank();
                });
        if (!modelKeyConfigured) {
            violations.add("aioa.model.key(模型 API Key 加密): 未配置 AIOA_MODEL_KEY_ENC_KEY / "
                    + "AIOA_GITEE_TOKEN_ENC_KEY，使用内置开发 fallback 密钥（弱保护）");
        }

        try {
            SecretStrengthValidator.enforce(violations, environment.getActiveProfiles());
        } catch (IllegalStateException e) {
            // 仅 prod 会走到这里
            throw e;
        }
        if (!violations.isEmpty()) {
            log.warn("检测到弱密钥/占位密钥（非生产环境仅告警，不阻断启动）：\n{}",
                    String.join("\n", violations));
        }
    }

    private void checkSeed() {
        try {
            SysUser admin = sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                    .eq(SysUser::getUsername, SEED_USERNAME));
            if (admin == null) {
                log.warn("seed user '{}' not found, please run flyway migration", SEED_USERNAME);
                return;
            }
            boolean matched = passwordEncoder.matches(SEED_PASSWORD, admin.getPasswordHash());
            log.info("seed user '{}' password '{}' matches = {} (status={})",
                    SEED_USERNAME, SEED_PASSWORD, matched, admin.getStatus());
            if (!matched) {
                log.warn("seed password mismatch, please regenerate the bcrypt hash in V2__seed.sql");
            }
        } catch (Exception e) {
            log.warn("startup seed check skipped: {}", e.getMessage());
        }
    }
}
