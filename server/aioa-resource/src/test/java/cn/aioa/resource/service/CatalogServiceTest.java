package cn.aioa.resource.service;

import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.mapper.AiSkillMapper;
import cn.aioa.resource.mapper.SysConfigMapper;
import cn.aioa.security.AuthUser;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 专家目录 + 默认 AI（V62）单测。
 *
 * <p>锁死四类容易静默走偏的行为：
 * <ol>
 *   <li><b>回落次序</b>：本租户有行就用本租户；本租户为空才回落全局 —— 反过来（或两边都要、去重不当）
 *       会让租户自建目录里凭空多出全局专家，属于「多给了别人不该看的东西」。</li>
 *   <li><b>「有行留空」≠「没有这一行」</b>：前者是管理员明确不做兜底，必须尊重；
 *       后者只是参数还没物化，才继续回落。两者混同会导致「关不掉兜底」或「全新环境没兜底」。</li>
 *   <li><b>默认 AI 必须在列表里</b>：配置指向的专家若不在本租户目录，要从全局补一条并置顶；
 *       指向根本不存在的专家则静默降级（不标记、不抛错）。</li>
 *   <li><b>停用即不可见</b>（2026-09-24 修的缺陷）：管理端「停用」写的是
 *       {@code expert_config} 配置层，用户端必须读同一处；此前用户端只按
 *       {@code ai_expert.enabled} 列过滤，导致「管理员停用了、用户端照旧能用」。</li>
 * </ol>
 */
class CatalogServiceTest {

    private final AiExpertMapper expertMapper = mock(AiExpertMapper.class);
    private final AiSkillMapper skillMapper = mock(AiSkillMapper.class);
    private final SysConfigMapper sysConfigMapper = mock(SysConfigMapper.class);
    private final ExpertConfigService configService = mock(ExpertConfigService.class);
    private final CatalogService service =
            new CatalogService(expertMapper, skillMapper, sysConfigMapper, configService);

    /** 默认：配置层认为「都启用」；个别用例再按 key 覆盖成停用。 */
    private void assumeAllEnabled() {
        when(configService.isEnabled(any(), any(), any(), any(), any())).thenReturn(true);
    }

    private static AuthUser user(Long tenantId) {
        return AuthUser.builder().tenantId(tenantId).build();
    }

    private static AiExpert expert(long tenantId, String key, int sort) {
        AiExpert e = new AiExpert();
        e.setTenantId(tenantId);
        e.setExpertKey(key);
        e.setName(key);
        e.setEnabled(true);
        e.setSort(sort);
        return e;
    }

    private static SysConfig cfg(long tenantId, String value) {
        SysConfig c = new SysConfig();
        c.setTenantId(tenantId);
        c.setConfigKey(SysConfig.KEY_DEFAULT_EXPERT);
        c.setConfigValue(value);
        return c;
    }

    private static List<String> keys(List<AiExpert> rows) {
        return rows.stream().map(AiExpert::getExpertKey).toList();
    }

    @Test
    @DisplayName("本租户有专家 ⇒ 只用本租户（不查全局），且默认 AI 命中并被置顶")
    void tenantRowsWinAndDefaultIsMarked() {
        assumeAllEnabled();
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(5, "own-b", 20), expert(5, "own-a", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(5, "own-b"));

        List<AiExpert> out = service.experts(user(5L));

        assertEquals(List.of("own-b", "own-a"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()), "own-b 应被标记为默认");
        assertFalse(Boolean.TRUE.equals(out.get(1).getIsDefault()), "非默认项不应被标记");
        verify(expertMapper, times(1)).selectList(any());
    }

    @Test
    @DisplayName("本租户为空 ⇒ 回落全局（tenant_id=0）目录")
    void fallsBackToGlobalWhenTenantEmpty() {
        assumeAllEnabled();
        when(expertMapper.selectList(any()))
                .thenReturn(List.of())
                .thenReturn(List.of(expert(0, "general", 0), expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(null).thenReturn(cfg(0, "general"));

        List<AiExpert> out = service.experts(user(5L));

        assertEquals(List.of("general", "policy"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("参数「有行但留空」= 明确不做兜底 ⇒ 一个都不标记（不能偷偷回落到出厂值）")
    void blankValueMeansExplicitlyDisabled() {
        assumeAllEnabled();
        when(expertMapper.selectList(any())).thenReturn(List.of(expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, "   "));

        List<AiExpert> out = service.experts(user(0L));

        assertEquals(List.of("policy"), keys(out));
        assertFalse(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("参数行完全不存在（全新库）⇒ 用出厂内置 general，仍保证有兜底")
    void missingRowFallsBackToBuiltin() {
        assumeAllEnabled();
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(0, "policy", 10), expert(0, "general", 0)));
        when(sysConfigMapper.selectOne(any())).thenReturn(null);

        List<AiExpert> out = service.experts(user(0L));

        assertEquals(List.of("general", "policy"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("默认 AI 不在本租户目录 ⇒ 从全局补一条并置顶，保证它一定在列表里")
    void defaultExpertIsAppendedFromGlobalWhenMissingLocally() {
        assumeAllEnabled();
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(5, "own", 10)))
                .thenReturn(List.of(expert(0, "general", 0)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(5, "general"));

        List<AiExpert> out = service.experts(user(5L));

        assertEquals(List.of("general", "own"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
        assertEquals(2, out.size());
    }

    @Test
    @DisplayName("参数指向不存在的专家 ⇒ 静默降级：不标记、不抛错、目录原样")
    void unknownKeyDegradesSilently() {
        assumeAllEnabled();
        when(expertMapper.selectList(any())).thenReturn(List.of(expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, "not-exist"));

        List<AiExpert> out = service.experts(user(0L));

        assertEquals(List.of("policy"), keys(out));
        assertFalse(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("tenantId 为空 ⇒ 按平台默认租户(0) 处理")
    void nullTenantTreatedAsPlatform() {
        assumeAllEnabled();
        when(expertMapper.selectList(any())).thenReturn(List.of(expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, "policy"));

        List<AiExpert> out = service.experts(user(null));

        assertEquals(List.of("policy"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("同 sort 时保持原有相对次序（排序稳定，避免每次请求顺序抖动）")
    void sortIsStableForEqualSortValues() {
        assumeAllEnabled();
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(0, "p1", 10), expert(0, "p2", 10), expert(0, "p3", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, ""));

        List<AiExpert> out = service.experts(user(0L));

        assertEquals(List.of("p1", "p2", "p3"), keys(out));
    }

    // ------------------------------------------------ 2026-09-24 缺陷：停用必须对用户端生效

    @Test
    @DisplayName("配置层停用的专家 ⇒ 用户端目录里看不到它（管理端停用必须对用户端生效）")
    void disabledExpertIsHiddenFromUserEnd() {
        assumeAllEnabled();
        when(configService.isEnabled(any(), any(), any(), any(), eq("t1"))).thenReturn(false);
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(5, "t1", 10), expert(5, "t2", 20)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(5, ""));

        List<AiExpert> out = service.experts(user(5L));

        assertEquals(List.of("t2"), keys(out), "停用的 t1 不应出现在用户端目录里");
    }

    @Test
    @DisplayName("本租户可用专家全部被停用 ⇒ 视为空缺，回落全局目录（而不是把停用的补回来）")
    void allDisabledFallsBackToGlobalAndNeverResurrectsDisabled() {
        assumeAllEnabled();
        when(configService.isEnabled(any(), any(), any(), any(), eq("t1"))).thenReturn(false);
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(5, "t1", 10)))
                .thenReturn(List.of(expert(0, "general", 0)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(5, ""));

        List<AiExpert> out = service.experts(user(5L));

        assertEquals(List.of("general"), keys(out));
    }

    @Test
    @DisplayName("默认 AI 被停用 ⇒ 不能绕过停用把它从全局补回来（目录静默降级）")
    void disabledDefaultExpertIsNotForceAppended() {
        assumeAllEnabled();
        when(configService.isEnabled(any(), any(), any(), any(), eq("general"))).thenReturn(false);
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(5, "own", 10)))
                .thenReturn(List.of(expert(0, "general", 0)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(5, "general"));

        List<AiExpert> out = service.experts(user(5L));

        assertEquals(List.of("own"), keys(out), "被停用的默认 AI 不应被强行补进目录");
        assertFalse(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }
}
