package cn.aioa.resource.service;

import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.mapper.AiSkillMapper;
import cn.aioa.resource.mapper.SysConfigMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 专家目录 + 默认 AI（V62）单测。
 *
 * <p>锁死三类容易静默走偏的行为：
 * <ol>
 *   <li><b>回落次序</b>：本租户有行就用本租户；本租户为空才回落全局 —— 反过来（或两边都要、去重不当）
 *       会让租户自建目录里凭空多出全局专家，属于「多给了别人不该看的东西」。</li>
 *   <li><b>「有行留空」≠「没有这一行」</b>：前者是管理员明确不做兜底，必须尊重；
 *       后者只是参数还没物化，才继续回落。两者混同会导致「关不掉兜底」或「全新环境没兜底」。</li>
 *   <li><b>默认 AI 必须在列表里</b>：配置指向的专家若不在本租户目录，要从全局补一条并置顶；
 *       指向根本不存在的专家则静默降级（不标记、不抛错）。</li>
 * </ol>
 */
class CatalogServiceTest {

    private final AiExpertMapper expertMapper = mock(AiExpertMapper.class);
    private final AiSkillMapper skillMapper = mock(AiSkillMapper.class);
    private final SysConfigMapper sysConfigMapper = mock(SysConfigMapper.class);
    private final CatalogService service = new CatalogService(expertMapper, skillMapper, sysConfigMapper);

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
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(5, "own-b", 20), expert(5, "own-a", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(5, "own-b"));

        List<AiExpert> out = service.experts(5L);

        assertEquals(List.of("own-b", "own-a"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()), "own-b 应被标记为默认");
        assertFalse(Boolean.TRUE.equals(out.get(1).getIsDefault()), "非默认项不应被标记");
        verify(expertMapper, times(1)).selectList(any());
    }

    @Test
    @DisplayName("本租户为空 ⇒ 回落全局（tenant_id=0）目录")
    void fallsBackToGlobalWhenTenantEmpty() {
        when(expertMapper.selectList(any()))
                .thenReturn(List.of())
                .thenReturn(List.of(expert(0, "general", 0), expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(null).thenReturn(cfg(0, "general"));

        List<AiExpert> out = service.experts(5L);

        assertEquals(List.of("general", "policy"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("参数「有行但留空」= 明确不做兜底 ⇒ 一个都不标记（不能偷偷回落到出厂值）")
    void blankValueMeansExplicitlyDisabled() {
        when(expertMapper.selectList(any())).thenReturn(List.of(expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, "   "));

        List<AiExpert> out = service.experts(0L);

        assertEquals(List.of("policy"), keys(out));
        assertFalse(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("参数行完全不存在（全新库）⇒ 用出厂内置 general，仍保证有兜底")
    void missingRowFallsBackToBuiltin() {
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(0, "policy", 10), expert(0, "general", 0)));
        when(sysConfigMapper.selectOne(any())).thenReturn(null);

        List<AiExpert> out = service.experts(0L);

        assertEquals(List.of("general", "policy"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("默认 AI 不在本租户目录 ⇒ 从全局补一条并置顶，保证它一定在列表里")
    void defaultExpertIsAppendedFromGlobalWhenMissingLocally() {
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(5, "own", 10)))
                .thenReturn(List.of(expert(0, "general", 0)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(5, "general"));

        List<AiExpert> out = service.experts(5L);

        assertEquals(List.of("general", "own"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
        assertEquals(2, out.size());
    }

    @Test
    @DisplayName("参数指向不存在的专家 ⇒ 静默降级：不标记、不抛错、目录原样")
    void unknownKeyDegradesSilently() {
        when(expertMapper.selectList(any())).thenReturn(List.of(expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, "not-exist"));

        List<AiExpert> out = service.experts(0L);

        assertEquals(List.of("policy"), keys(out));
        assertFalse(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("tenantId 为空 ⇒ 按平台默认租户(0) 处理")
    void nullTenantTreatedAsPlatform() {
        when(expertMapper.selectList(any())).thenReturn(List.of(expert(0, "policy", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, "policy"));

        List<AiExpert> out = service.experts(null);

        assertEquals(List.of("policy"), keys(out));
        assertTrue(Boolean.TRUE.equals(out.get(0).getIsDefault()));
    }

    @Test
    @DisplayName("同 sort 时保持原有相对次序（排序稳定，避免每次请求顺序抖动）")
    void sortIsStableForEqualSortValues() {
        when(expertMapper.selectList(any()))
                .thenReturn(List.of(expert(0, "p1", 10), expert(0, "p2", 10), expert(0, "p3", 10)));
        when(sysConfigMapper.selectOne(any())).thenReturn(cfg(0, ""));

        List<AiExpert> out = service.experts(0L);

        assertEquals(List.of("p1", "p2", "p3"), keys(out));
    }
}
