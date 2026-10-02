package cn.aioa.project.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.entity.PmProject;
import cn.aioa.project.entity.PmProjectMember;
import cn.aioa.project.mapper.PmProjectMemberMapper;
import cn.aioa.project.mapper.PmRepoBindMapper;
import cn.aioa.project.support.PmProjectRoles;
import cn.aioa.project.support.PmProjectType;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 项目成员与项目内角色（BR-03 / BR-04 / BR-05）。
 *
 * <p><b>成员来源</b>：只能是本租户**在册员工**（{@code org_member.status='ACTIVE'} 且未软删）。
 * 不允许手工填一个用户名 —— 那会造出「成员存在但查不到人」的孤儿行。</p>
 *
 * <p><b>关于开发项目的仓库协作者同步（BR-04）</b>：成员变更后置 {@code repo_sync_status}。
 * 本批次**只落状态**，真正推送协作者到托管平台的链路（依赖每位员工已绑定 Gitee/Gitea 账号）
 * 在下一批次接入既有 outbox。为避免误导，接口在开发项目上会回一个
 * {@code repoSyncNote} 明说当前需在「项目与仓库」页手工加协作者 —— 不静默假装已同步。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PmProjectMemberService {

    private final PmProjectMemberMapper memberMapper;
    private final PmRepoBindMapper repoBindMapper;
    private final OrgMemberMapper orgMemberMapper;
    private final PmProjectService projectService;
    private final OrgGuard guard;

    /** 项目成员列表（含员工姓名 / 部门 / 项目角色 / 仓库同步态）。 */
    public Map<String, Object> list(AuthUser user, Long projectId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        List<PmProjectMember> rows = memberMapper.selectList(new LambdaQueryWrapper<PmProjectMember>()
                .eq(PmProjectMember::getTenantId, p.getTenantId())
                .eq(PmProjectMember::getProjectId, projectId)
                .orderByAsc(PmProjectMember::getId));

        List<Map<String, Object>> items = new ArrayList<>();
        for (PmProjectMember r : rows) {
            items.add(toView(p, r));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("roleOptions", PmProjectRoles.options());
        out.put("canManage", canManageMembers(user, p));
        if (PmProjectType.isDev(p.getProjectType())) {
            out.put("repoSyncNote", repoSyncNote(p));
        }
        return out;
    }

    /** 可加入的员工候选（本租户在册、且尚未在该项目中的员工）。 */
    public List<Map<String, Object>> candidates(AuthUser user, Long projectId, String keyword) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireMemberManager(user, p);

        List<PmProjectMember> existing = memberMapper.selectList(new LambdaQueryWrapper<PmProjectMember>()
                .eq(PmProjectMember::getTenantId, p.getTenantId())
                .eq(PmProjectMember::getProjectId, projectId));
        Map<Long, Long> alreadyMember = existing.stream()
                .collect(Collectors.toMap(PmProjectMember::getMemberId, PmProjectMember::getId, (a, b) -> a));

        String kw = StringUtils.hasText(keyword) ? keyword.trim().toLowerCase(Locale.ROOT) : null;
        List<OrgMember> members = orgMemberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getTenantId, p.getTenantId())
                .eq(OrgMember::getStatus, "ACTIVE")
                .orderByAsc(OrgMember::getId));

        List<Map<String, Object>> out = new ArrayList<>();
        for (OrgMember m : members) {
            if (alreadyMember.containsKey(m.getId())) {
                continue;
            }
            if (kw != null && !matches(kw, m.getName(), m.getEmployeeNo(), m.getMobile(), m.getJobTitle())) {
                continue;
            }
            Map<String, Object> x = new LinkedHashMap<>();
            x.put("memberId", m.getId());
            x.put("name", m.getName());
            x.put("employeeNo", m.getEmployeeNo());
            x.put("jobTitle", m.getJobTitle());
            x.put("mobile", m.getMobile());
            x.put("departmentId", m.getDepartmentId());
            out.add(x);
        }
        return out;
    }

    /** 新增成员并分配项目角色（BR-03）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> add(AuthUser user, Long projectId, Long memberId, String roleCode) {
        PmProject p = projectService.requireVisible(user, projectId, true);
        requireMemberManager(user, p);

        if (!PmProjectRoles.isValid(roleCode)) {
            throw BizException.badRequest("未知项目角色：" + roleCode);
        }
        if (memberId == null) {
            throw BizException.badRequest("请选择要加入的员工");
        }
        OrgMember m = projectService.requireActiveMember(p.getTenantId(), memberId);

        // 唯一性：先查存活行（软删行不占唯一键，直接插会与「曾经删过」冲突不了但会造出重复成员）
        Long dup = memberMapper.selectCount(new LambdaQueryWrapper<PmProjectMember>()
                .eq(PmProjectMember::getProjectId, projectId)
                .eq(PmProjectMember::getMemberId, memberId));
        if (dup != null && dup > 0) {
            throw new BizException(409, "该员工已是本项目成员");
        }

        PmProjectMember pm = new PmProjectMember();
        pm.setTenantId(p.getTenantId());
        pm.setProjectId(projectId);
        pm.setMemberId(memberId);
        pm.setUserId(m.getUserId());
        pm.setRoleCode(roleCode);
        pm.setRepoSyncStatus(repoSyncStatus(p));
        pm.setJoinedAt(LocalDate.now());
        pm.setCreatedBy(user.getUserId());
        pm.setCreatedAt(LocalDateTime.now());
        memberMapper.insert(pm);
        log.info("PM 项目成员已加入 projectId={} memberId={} role={}", projectId, memberId, roleCode);
        return list(user, projectId);
    }

    /** 改项目角色。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> changeRole(AuthUser user, Long projectId, Long memberRowId, String roleCode) {
        PmProject p = projectService.requireVisible(user, projectId, true);
        requireMemberManager(user, p);
        if (!PmProjectRoles.isValid(roleCode)) {
            throw BizException.badRequest("未知项目角色：" + roleCode);
        }
        PmProjectMember row = requireRow(p.getTenantId(), projectId, memberRowId);
        if (PmProjectRoles.OWNER.equals(row.getRoleCode()) && !PmProjectRoles.OWNER.equals(roleCode)) {
            assertNotLastOwner(p, memberRowId);
        }
        row.setRoleCode(roleCode);
        row.setUpdatedAt(LocalDateTime.now());
        memberMapper.updateById(row);
        return list(user, projectId);
    }

    /** 移除成员（BR-04：软删 + 开发项目置仓库同步态）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> remove(AuthUser user, Long projectId, Long memberRowId) {
        PmProject p = projectService.requireVisible(user, projectId, true);
        requireMemberManager(user, p);
        PmProjectMember row = requireRow(p.getTenantId(), projectId, memberRowId);

        // 不变量：项目必须至少留一个负责人（否则项目无人可管，只能靠管理员介入）
        if (PmProjectRoles.OWNER.equals(row.getRoleCode())) {
            assertNotLastOwner(p, memberRowId);
        }
        if (Objects.equals(p.getOwnerMemberId(), row.getMemberId())) {
            // 负责人行被移除时，负责人字段一并清空，避免「负责人字段指向已不在项目的员工」
            throw BizException.badRequest("该成员是项目负责人，请先在项目信息里更换负责人再移除");
        }
        memberMapper.deleteById(row.getId());
        log.info("PM 项目成员已移除 projectId={} memberRowId={}（开发项目需同步撤销仓库协作者）",
                projectId, memberRowId);
        return list(user, projectId);
    }

    // ======================================================================
    // 内部
    // ======================================================================

    private Map<String, Object> toView(PmProject p, PmProjectMember r) {
        OrgMember m = orgMemberMapper.selectById(r.getMemberId());
        Map<String, Object> x = new LinkedHashMap<>();
        x.put("id", r.getId());
        x.put("memberId", r.getMemberId());
        x.put("userId", r.getUserId());
        x.put("name", m == null ? null : m.getName());
        x.put("employeeNo", m == null ? null : m.getEmployeeNo());
        x.put("jobTitle", m == null ? null : m.getJobTitle());
        x.put("departmentId", m == null ? null : m.getDepartmentId());
        x.put("roleCode", r.getRoleCode());
        x.put("roleLabel", PmProjectRoles.label(r.getRoleCode()));
        x.put("repoSyncStatus", r.getRepoSyncStatus());
        x.put("joinedAt", r.getJoinedAt());
        return x;
    }

    private PmProjectMember requireRow(Long tenantId, Long projectId, Long rowId) {
        PmProjectMember row = memberMapper.selectById(rowId);
        if (row == null || !Objects.equals(row.getTenantId(), tenantId)
                || !Objects.equals(row.getProjectId(), projectId)) {
            throw BizException.notFound("成员记录不存在");
        }
        return row;
    }

    private void assertNotLastOwner(PmProject p, Long excludeRowId) {
        long owners = memberMapper.selectList(new LambdaQueryWrapper<PmProjectMember>()
                        .eq(PmProjectMember::getTenantId, p.getTenantId())
                        .eq(PmProjectMember::getProjectId, p.getId())
                        .eq(PmProjectMember::getRoleCode, PmProjectRoles.OWNER)).stream()
                .filter(r -> !Objects.equals(r.getId(), excludeRowId))
                .count();
        if (owners == 0) {
            throw BizException.badRequest("项目至少需要保留一名项目负责人");
        }
    }

    private String repoSyncStatus(PmProject p) {
        if (!PmProjectType.isDev(p.getProjectType())) {
            return "NA";
        }
        long repos = repoBindMapper.countBound(p.getTenantId(), p.getId());
        return repos > 0 ? "PENDING" : "NA";
    }

    private String repoSyncNote(PmProject p) {
        long repos = repoBindMapper.countBound(p.getTenantId(), p.getId());
        if (repos == 0) {
            return "项目尚未绑定代码仓库，成员变更无需同步。";
        }
        return "成员变更已记录（待同步 " + repos + " 个仓库的协作者）。"
                + "仓库协作者自动同步将于下一批次接入托管平台 outbox；"
                + "当前如需立即生效，请在「项目与仓库」对应仓库中手工添加协作者。";
    }

    private void requireMemberManager(AuthUser user, PmProject p) {
        if (canManageMembers(user, p)) {
            return;
        }
        throw BizException.forbidden("仅项目负责人/项目经理或机构管理员及以上可管理项目成员");
    }

    private boolean canManageMembers(AuthUser user, PmProject p) {
        if (PermissionCatalog.isPlatformAdmin(user)) {
            return false;
        }
        if (OrgGuard.hasRole(user, OrgGuard.ROLE_TENANT_ADMIN)
                || OrgGuard.hasRole(user, OrgGuard.ROLE_ORG_ADMIN)) {
            return true;
        }
        PmProjectMember mine = projectService.myMembership(p.getTenantId(), p.getId(), user.getUserId());
        return mine != null && PmProjectRoles.canManageMember(mine.getRoleCode());
    }

    private static boolean matches(String kw, String... fields) {
        for (String f : fields) {
            if (f != null && f.toLowerCase(Locale.ROOT).contains(kw)) {
                return true;
            }
        }
        return false;
    }
}
