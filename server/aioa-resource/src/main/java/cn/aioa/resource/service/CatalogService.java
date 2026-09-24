package cn.aioa.resource.service;

import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.AiSkill;
import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.mapper.AiSkillMapper;
import cn.aioa.resource.mapper.SysConfigMapper;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 * 专家与技能目录。两者都是租户级配置（不区分用户），按 sort 升序返回。
 *
 * <p><b>「专家是否上架」的判据只有一处</b>（铁律 #1）：本类的 {@link #experts(AuthUser)}
 * 先按 {@code ai_expert.enabled} 列取行（行级总闸），再逐条问
 * {@link ExpertConfigService#isEnabled}（配置层开关，管理端「启用 / 停用」写的就是它）。
 * 两者都为真才下发。管理端的专家列表
 * （{@code ExpertConfigController#experts}）走的是同一个 {@code ExpertConfigService}
 * 判据，因此「管理端看到的状态」与「用户端看到的状态」不会打架。</p>
 *
 * <p>专家目录承载「默认 AI」语义（V62）：未选择任何专家时，用户端应落到
 * {@link SysConfig#KEY_DEFAULT_EXPERT} 指向的那位专家。该判定只在
 * {@link #experts(AuthUser)} 一处完成，前端只消费 {@code isDefault} 标记，
 * 避免「谁能兜底」在两个地方各判一次而打架。</p>
 */
@Service
@RequiredArgsConstructor
public class CatalogService {

    private final AiExpertMapper expertMapper;
    private final AiSkillMapper skillMapper;
    private final SysConfigMapper sysConfigMapper;
    private final ExpertConfigService configService;

    /**
     * 当前用户可见的专家目录（含默认 AI 标记）。
     *
     * <p>四步：
     * <ol>
     *   <li><b>可用性过滤</b>：行级 {@code enabled} 列 + 配置层 {@code enabled}（分片见
     *       {@link #availableExperts}）。停用的专家对用户端**不可见**，因此也就选不到、用不了。</li>
     *   <li><b>本租户优先、全局兜底</b>：本租户没有任何<b>可用</b>专家时回落到平台默认
     *       （{@code tenant_id=0}）；项目既有范式是「租户覆盖 + 回落全局」，
     *       因此不为租户播种副本行，回落路径天然被既有数据持续验证。</li>
     *   <li><b>标记默认 AI</b>：把 {@code chat.default_expert_key} 命中的那条置 {@code isDefault=true}；
     *       命中不到（本租户自建目录里没有该 key）则从全局目录补一条，保证兜底对象「一定在列表里」。</li>
     *   <li><b>默认置顶</b>：其余按 {@code sort}。默认 AI 排最前与「未选功能时的第一去处」一致。</li>
     * </ol>
     *
     * <p>降级约定：参数缺失 / 为空 / 指向不存在的 key ⇒ <b>不标记、不报错</b>，
     * 退化为普通列表（用户端有本地兜底会话，不会因此白屏或弹错误）。
     */
    public List<AiExpert> experts(AuthUser user) {
        long tid = tenantOf(user);

        List<AiExpert> rows = availableExperts(user, tid);
        if (rows.isEmpty() && tid != 0L) {
            rows = availableExperts(user, 0L);
        }

        String defaultKey = defaultExpertKey(tid);
        if (defaultKey == null || defaultKey.isBlank()) {
            return rows;
        }
        String key = defaultKey.trim();

        List<AiExpert> list = new ArrayList<>(rows);
        AiExpert target = list.stream()
                .filter(e -> key.equals(e.getExpertKey()))
                .findFirst()
                .orElse(null);
        if (target == null) {
            // 本租户目录里没有这位默认 AI：从全局目录取一份并补进来。
            // 这一步保证「内置的默认 AI」在任何租户下都拿得到，不因租户自建目录而失效。
            // 注意仍要走可用性过滤：默认 AI 被停用时**不能**绕过停用把它补回来。
            target = availableExperts(user, 0L).stream()
                    .filter(e -> key.equals(e.getExpertKey()))
                    .findFirst()
                    .orElse(null);
            if (target == null) {
                return rows; // 配置指向了不存在的专家（或被停用）→ 静默降级，不改动目录
            }
            list.add(target);
        }
        target.setIsDefault(true);
        // 置顶：稳定排序（同 sort 保持原相对次序，避免每次请求顺序抖动）
        list.sort((a, b) -> {
            boolean da = Boolean.TRUE.equals(a.getIsDefault());
            boolean db = Boolean.TRUE.equals(b.getIsDefault());
            if (da != db) return da ? -1 : 1;
            Integer sa = a.getSort() == null ? 0 : a.getSort();
            Integer sb = b.getSort() == null ? 0 : b.getSort();
            return Integer.compare(sa, sb);
        });
        return list;
    }

    public List<AiSkill> skills(Long tenantId) {
        return skillMapper.selectList(new LambdaQueryWrapper<AiSkill>()
                .eq(AiSkill::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(AiSkill::getEnabled, true)
                .orderByAsc(AiSkill::getSort));
    }

    // ---------------- 内部 ----------------

    /**
     * 某租户下**对该用户可用**的专家。
     *
     * <p>两道闸：</p>
     * <ol>
     *   <li>SQL 层 {@code ai_expert.enabled = true} —— 行级总闸（专家行是否上架）；</li>
     *   <li>{@link ExpertConfigService#isEnabled} —— 配置层开关（某租户 / 机构 / 部门 / 个人
     *       是否停用了它）。管理端表格里的那个开关写的就是这一层。</li>
     * </ol>
     */
    private List<AiExpert> availableExperts(AuthUser user, long tenantId) {
        return expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                        .eq(AiExpert::getTenantId, tenantId)
                        .eq(AiExpert::getEnabled, true)
                        .orderByAsc(AiExpert::getSort))
                .stream()
                .filter(e -> configService.isEnabled(tenantOf(user), institutionOf(user),
                        departmentOf(user), userIdOf(user), e.getExpertKey()))
                .toList();
    }

    private static long tenantOf(AuthUser user) {
        return user == null || user.getTenantId() == null ? 0L : user.getTenantId();
    }

    private static Long institutionOf(AuthUser user) {
        return user == null ? null : user.getInstitutionId();
    }

    private static Long departmentOf(AuthUser user) {
        return user == null ? null : user.getDepartmentId();
    }

    private static Long userIdOf(AuthUser user) {
        return user == null ? null : user.getUserId();
    }

    /**
     * 解析默认 AI 的专家标识：本租户参数 → 平台默认参数 → 出厂内置。
     *
     * <p><b>public</b>：删除专家时要拦「默认 AI 不可删」，必须用同一判据 ——
     * 否则会出现「目录按 A 判默认、删除按 B 判默认」的两处口径（铁律 #1）。</p>
     *
     * <p>注意「有行但留空」与「没有这一行」是**两种不同含义**，不能都当没配：
     * 前者是管理员明确要求「不做兜底」，必须尊重（返回 null ⇒ 不标记）；
     * 后者只说明参数还没物化，才继续往平台默认、出厂内置回落。</p>
     *
     * <p>最后一档（出厂内置）是必要的：参数行是懒克隆的（租户首次访问管理端才拷一份），
     * 而用户端首屏就会调本接口 —— 若没有这一档，全新环境在管理员打开配置页之前拿不到默认 AI。</p>
     */
    public String defaultExpertKey(Long tenantId) {
        long tid = tenantId == null ? 0L : tenantId;
        SysConfig own = configRow(tid, SysConfig.KEY_DEFAULT_EXPERT);
        if (own != null) {
            return blankToNull(own.getConfigValue());
        }
        SysConfig platform = configRow(0L, SysConfig.KEY_DEFAULT_EXPERT);
        if (platform != null) {
            return blankToNull(platform.getConfigValue());
        }
        return SysConfig.DEFAULT_EXPERT_KEY;
    }

    private SysConfig configRow(long tenantId, String key) {
        return sysConfigMapper.selectOne(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, tenantId)
                .eq(SysConfig::getConfigKey, key)
                .last("limit 1"));
    }

    private static String blankToNull(String s) {
        return (s == null || s.isBlank()) ? null : s.trim();
    }
}
