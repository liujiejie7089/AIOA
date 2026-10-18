package cn.aios.chat.service;

import cn.aios.common.exception.BizException;
import cn.aios.org.entity.OrgInstitution;
import cn.aios.org.mapper.OrgInstitutionMapper;
import cn.aios.resource.mapper.SysConfigMapper;
import cn.aios.resource.mapper.SysOrgConfigMapper;
import cn.aios.security.AuthUser;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 机构作用域解析纯函数定点验收（需求二 · docs/44 §2.5 B 案）。
 *
 * <p>本类<b>不启动 Spring 上下文</b>：{@link OrgConfigService#resolveScopeInstitution} 与
 * {@link OrgConfigService#resolveWriteScope} 都是 static 纯函数，只依赖入参与
 * {@link PermissionCatalog} 的角色判定，不触碰 Mapper / 数据库。把作用域这一「越权判定点」
 * 单独钉死，确保「机构管理员钉死自己 / 传别人即 403 / 未绑机构即 403 / 可切者须属本租户」任何一条
 * 被破坏都会立刻变红。</p>
 */
class OrgConfigScopeTest {

    /** 本租户的机构集合（含跨租户越界判定用的「不在其中」的机构 9）。 */
    private static final Set<Long> TENANT_INSTITUTIONS = Set.of(3L, 4L, 5L);

    // 机构清单分支（buildInstitutions）定点所需：用真服务 + 假 Mapper 注入，不启动 Spring。
    private final SysConfigMapper configMapper = mock(SysConfigMapper.class);
    private final SysOrgConfigMapper orgConfigMapper = mock(SysOrgConfigMapper.class);
    private final OrgInstitutionMapper institutionMapper = mock(OrgInstitutionMapper.class);
    private final OrgConfigService service =
            new OrgConfigService(configMapper, orgConfigMapper, institutionMapper);

    private static AuthUser orgAdmin(Long instId) {
        return AuthUser.builder()
                .userId(1L).tenantId(7L).institutionId(instId)
                .roles(List.of("ROLE_ORG_ADMIN")).build();
    }

    private static AuthUser platformAdmin() {
        return AuthUser.builder()
                .userId(2L).tenantId(7L)
                .roles(List.of("ROLE_ADMIN")).build();
    }

    // ------------------------------------------------------------ 机构管理员（钉死本机构）

    @Test
    @DisplayName("机构管理员 + 请求本机构 → 返回本机构")
    void orgAdminRequestsOwn() {
        Long r = OrgConfigService.resolveScopeInstitution(orgAdmin(3L), 3L, TENANT_INSTITUTIONS);
        assertEquals(3L, r);
    }

    @Test
    @DisplayName("★机构管理员 + 请求别的机构 → 抛 403（不是静默降级）")
    void orgAdminRequestsOther() {
        BizException ex = assertThrows(BizException.class,
                () -> OrgConfigService.resolveScopeInstitution(orgAdmin(3L), 5L, TENANT_INSTITUTIONS));
        assertEquals(403, ex.getCode());
    }

    @Test
    @DisplayName("★机构管理员 + institutionId 为 null（未绑机构）→ 抛 403「账号未绑定机构」")
    void orgAdminUnbound() {
        BizException ex = assertThrows(BizException.class,
                () -> OrgConfigService.resolveScopeInstitution(orgAdmin(null), null, TENANT_INSTITUTIONS));
        assertEquals(403, ex.getCode());
    }

    // ------------------------------------------------------------ 平台/租户管理员（可切机构）

    @Test
    @DisplayName("平台管理员 + 请求本租户某机构 → 返回该机构")
    void platformAdminRequestsTenantInstitution() {
        Long r = OrgConfigService.resolveScopeInstitution(platformAdmin(), 4L, TENANT_INSTITUTIONS);
        assertEquals(4L, r);
    }

    @Test
    @DisplayName("★平台管理员 + 请求不在本租户的机构 → 抛错（403/404 之一，断言实际异常类型）")
    void platformAdminRequestsForeignInstitution() {
        BizException ex = assertThrows(BizException.class,
                () -> OrgConfigService.resolveScopeInstitution(platformAdmin(), 9L, TENANT_INSTITUTIONS));
        // 越界一律 forbidden（403）；断言实际异常类型与码，避免「抛了别的错也算过」
        assertEquals(403, ex.getCode());
    }

    @Test
    @DisplayName("★institutionId 省略且可切机构 → 写操作判 400「请先选择机构」")
    void switchableOmitOnWrite() {
        BizException ex = assertThrows(BizException.class,
                () -> OrgConfigService.resolveWriteScope(platformAdmin(), null, TENANT_INSTITUTIONS));
        assertEquals(400, ex.getCode());
    }

    @Test
    @DisplayName("（补充）机构管理员省略 institutionId → 钉死本机构，写操作不触发 400")
    void orgAdminOmitOnWritePinned() {
        Long r = OrgConfigService.resolveWriteScope(orgAdmin(3L), null, TENANT_INSTITUTIONS);
        assertEquals(3L, r);
    }

    // ------------------------------------------------------------ 机构清单分支（buildInstitutions）
    // 修复前该方法的 scoped 条件写反：机构管理员拿到了同租户全部机构。下面两条是该反转的回归锁，
    // 条件再被取反时两条都会变红。

    @Test
    @DisplayName("★机构管理员(scoped=true) → institutions 恰好 1 个，且是本人机构（不是同租户全部）")
    void orgAdminSeesOnlyOwnInstitution() {
        AuthUser user = orgAdmin(3L);
        OrgInstitution me = new OrgInstitution();
        me.setId(3L);
        me.setTenantId(7L);
        me.setName("我的机构");
        when(institutionMapper.selectById(3L)).thenReturn(me);

        List<OrgConfigService.InstitutionDTO> list = service.buildInstitutions(user, 7L, true);

        assertEquals(1, list.size(), "机构管理员只应看到本人机构");
        assertEquals(3L, list.get(0).getId());
        assertEquals("我的机构", list.get(0).getName());
        verify(institutionMapper).selectById(3L);
    }

    @Test
    @DisplayName("★平台/租户管理员(scoped=false) → institutions 为本租户全部机构，按 id 升序")
    void platformAdminSeesAllTenantInstitutions() {
        AuthUser user = platformAdmin();
        // 故意乱序给出：验证「按 id 升序」由方法自身的内存排序保证，而非依赖入参顺序
        List<OrgInstitution> all = new ArrayList<>();
        for (long id : new long[]{5L, 3L, 4L}) {
            OrgInstitution o = new OrgInstitution();
            o.setId(id);
            o.setTenantId(7L);
            o.setName("inst-" + id);
            all.add(o);
        }
        when(institutionMapper.selectList(any())).thenReturn(all);

        List<OrgConfigService.InstitutionDTO> list = service.buildInstitutions(user, 7L, false);

        // 核心回归锁：返回「本租户全部」而非「只本人」，且按 id 升序（不是乱序）
        assertEquals(List.of(3L, 4L, 5L),
                list.stream().map(OrgConfigService.InstitutionDTO::getId).toList(),
                "应返回本租户全部机构并按 id 升序（不是只本人、也不是乱序）");
        verify(institutionMapper).selectList(any());
    }
}
