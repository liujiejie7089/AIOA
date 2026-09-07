package cn.aioa.boot.runner;

import cn.aioa.admin.entity.SysUser;
import cn.aioa.admin.mapper.SysUserMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

/**
 * 启动自检：校验种子用户 admin 的密码哈希与 "Admin@123" 一致（便于确认 Flyway 种子数据可用）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class StartupCheckRunner implements ApplicationRunner {

    private static final String SEED_USERNAME = "admin";
    private static final String SEED_PASSWORD = "Admin@123";

    private final SysUserMapper sysUserMapper;
    private final PasswordEncoder passwordEncoder;

    @Override
    public void run(ApplicationArguments args) {
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
