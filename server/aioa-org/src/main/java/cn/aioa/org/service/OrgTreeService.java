package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.support.AccountProvisioner;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 组织机构管理（FR-G）：
 *   G1 部门树（层级 ≤ 5，物化路径支撑子树迁移）
 *   G2 员工管理（增删改查，逻辑删除）
 *   G3 批量导入（失败清单逐行返回，成功率 ≥ 99%）
 *   G4 团队（二期）
 *
 * 机构硬边界：所有方法入口先经 institutionId 断言，越界统一 404。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrgTreeService {

    /** FR-G1：部门层级上限。 */
    public static final int MAX_DEPTH = 5;

    private final OrgDepartmentMapper deptMapper;
    private final OrgMemberMapper memberMapper;
    private final AccountProvisioner accounts;
    private final AuditRecorder audit;

    // ------------------------------------------------------------------ G1 部门树

    public Map<String, Object> tree(Long institutionId) {
        List<OrgDepartment> all = deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId)
                .orderByAsc(OrgDepartment::getSort)
                .orderByAsc(OrgDepartment::getId));
        Map<Long, Map<String, Object>> nodes = new LinkedHashMap<>();
        for (OrgDepartment d : all) {
            Map<String, Object> n = new LinkedHashMap<>();
            n.put("id", d.getId());
            n.put("institutionId", d.getInstitutionId());
            n.put("parentId", d.getParentId());
            n.put("name", d.getName());
            n.put("code", d.getCode());
            n.put("level", d.getLevel());
            n.put("path", d.getPath());
            n.put("leaderUserId", d.getLeaderUserId());
            n.put("leaderName", d.getLeaderName());
            n.put("sort", d.getSort());
            n.put("status", d.getStatus());
            n.put("memberCount", memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                    .eq(OrgMember::getDepartmentId, d.getId())));
            n.put("children", new ArrayList<Map<String, Object>>());
            nodes.put(d.getId(), n);
        }
        List<Map<String, Object>> roots = new ArrayList<>();
        for (OrgDepartment d : all) {
            Map<String, Object> n = nodes.get(d.getId());
            Map<String, Object> parent = d.getParentId() == null ? null : nodes.get(d.getParentId());
            if (parent == null) {
                roots.add(n);
            } else {
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> kids = (List<Map<String, Object>>) parent.get("children");
                kids.add(n);
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", all.size());
        out.put("maxDepth", all.stream().mapToInt(d -> d.getLevel() == null ? 1 : d.getLevel()).max().orElse(0));
        out.put("depthLimit", MAX_DEPTH);
        out.put("flat", all);
        out.put("tree", roots);
        return out;
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> createDept(Long institutionId, AuthUser actor, Map<String, Object> body) {
        String name = Vals.require(body, "name", "部门名称");
        Long parentId = Vals.lng(body, "parentId", 0L);
        OrgDepartment parent = parentId == null || parentId == 0L ? null : requireDept(institutionId, parentId);
        int level = parent == null ? 1 : (parent.getLevel() == null ? 1 : parent.getLevel()) + 1;
        if (level > MAX_DEPTH) {
            throw BizException.badRequest("部门层级不得超过 " + MAX_DEPTH + " 层（FR-G1）");
        }
        checkDeptCode(institutionId, Vals.str(body, "code"), null);

        OrgDepartment d = new OrgDepartment();
        d.setTenantId(actor.getTenantId() == null ? 0L : actor.getTenantId());
        d.setInstitutionId(institutionId);
        d.setParentId(parent == null ? 0L : parent.getId());
        d.setName(name);
        d.setCode(Vals.str(body, "code"));
        d.setLevel(level);
        d.setPath("/");
        d.setLeaderUserId(Vals.lngObj(body, "leaderUserId"));
        d.setLeaderName(Vals.str(body, "leaderName"));
        d.setSort(Vals.integer(body, "sort", 0));
        d.setStatus("ACTIVE");
        d.setCreatedAt(LocalDateTime.now());
        d.setCreatedBy(actor.getUserId());
        deptMapper.insert(d);
        // path 依赖自增 id，插入后回填
        d.setPath(parent == null ? "/" + d.getId() + "/" : parent.getPath() + d.getId() + "/");
        d.setUpdatedAt(LocalDateTime.now());
        deptMapper.updateById(d);

        audit.record(d.getTenantId(), institutionId, actor, "DEPT_CREATE", "ORG_DEPARTMENT", d.getId(),
                "新建部门「" + name + "」（第 " + level + " 层）", null, d);
        return view(d);
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateDept(Long institutionId, Long id, AuthUser actor,
                                          Map<String, Object> body) {
        OrgDepartment d = requireDept(institutionId, id);
        OrgDepartment before = copy(d);
        if (Vals.str(body, "name") != null) {
            d.setName(Vals.str(body, "name"));
        }
        if (body != null && body.containsKey("code")) {
            String code = Vals.str(body, "code");
            checkDeptCode(institutionId, code, id);
            d.setCode(code);
        }
        if (body != null && body.containsKey("leaderUserId")) {
            d.setLeaderUserId(Vals.lngObj(body, "leaderUserId"));
            d.setLeaderName(Vals.str(body, "leaderName"));
        }
        if (body != null && body.containsKey("sort")) {
            d.setSort(Vals.integer(body, "sort", d.getSort() == null ? 0 : d.getSort()));
        }
        if (Vals.str(body, "status") != null) {
            d.setStatus(Vals.str(body, "status"));
        }
        if (body != null && body.containsKey("parentId")) {
            Long newParent = Vals.lng(body, "parentId", 0L);
            if (!java.util.Objects.equals(newParent, d.getParentId())) {
                moveInternal(institutionId, d, newParent);
            }
        }
        d.setUpdatedAt(LocalDateTime.now());
        deptMapper.updateById(d);

        audit.record(d.getTenantId(), institutionId, actor, "DEPT_UPDATE", "ORG_DEPARTMENT", id,
                "编辑部门「" + d.getName() + "」", before, d);
        return view(d);
    }

    /** FR-G1：调整上级部门，同步迁移子树 path 与 level。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> moveDept(Long institutionId, Long id, Long newParentId, AuthUser actor) {
        OrgDepartment d = requireDept(institutionId, id);
        OrgDepartment before = copy(d);
        moveInternal(institutionId, d, newParentId);
        d.setUpdatedAt(LocalDateTime.now());
        deptMapper.updateById(d);
        audit.record(d.getTenantId(), institutionId, actor, "DEPT_MOVE", "ORG_DEPARTMENT", id,
                "调整部门「" + d.getName() + "」上级为 "
                        + (newParentId == null || newParentId == 0L ? "根" : "#" + newParentId), before, d);
        return tree(institutionId);
    }

    private void moveInternal(Long institutionId, OrgDepartment d, Long newParentId) {
        long target = newParentId == null ? 0L : newParentId;
        if (target == d.getId()) {
            throw BizException.badRequest("上级部门不能是自己");
        }
        OrgDepartment parent = target == 0L ? null : requireDept(institutionId, target);
        if (parent != null && d.getPath() != null && parent.getPath() != null
                && parent.getPath().startsWith(d.getPath())) {
            throw BizException.badRequest("不能把部门移动到自己的下级");
        }
        int newLevel = parent == null ? 1 : (parent.getLevel() == null ? 1 : parent.getLevel()) + 1;
        int delta = newLevel - (d.getLevel() == null ? 1 : d.getLevel());

        // 子树最深层级（path 为物化路径 /a/b/，likeRight 命中全部后代）
        String rootPath = d.getPath() == null ? "/" + d.getId() + "/" : d.getPath();
        List<OrgDepartment> subtree = deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId)
                .likeRight(OrgDepartment::getPath, rootPath));
        int deepest = d.getLevel() == null ? 1 : d.getLevel();
        for (OrgDepartment x : subtree) {
            deepest = Math.max(deepest, x.getLevel() == null ? 1 : x.getLevel());
        }
        if (deepest + delta > MAX_DEPTH) {
            throw BizException.badRequest("迁移后子树最深将达 " + (deepest + delta)
                    + " 层，超过 " + MAX_DEPTH + " 层上限（FR-G1）");
        }

        String oldPath = rootPath;
        String newPath = parent == null ? "/" + d.getId() + "/" : parent.getPath() + d.getId() + "/";
        d.setParentId(target);
        d.setLevel(newLevel);
        d.setPath(newPath);

        for (OrgDepartment x : subtree) {
            if (x.getId().equals(d.getId())) {
                continue;
            }
            String p = x.getPath() == null ? "" : x.getPath();
            String suffix = p.startsWith(oldPath) ? p.substring(oldPath.length()) : p;
            OrgDepartment patch = new OrgDepartment();
            patch.setId(x.getId());
            patch.setLevel((x.getLevel() == null ? 1 : x.getLevel()) + delta);
            patch.setPath(newPath + suffix);
            patch.setUpdatedAt(LocalDateTime.now());
            deptMapper.updateById(patch);
        }
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> deleteDept(Long institutionId, Long id, AuthUser actor) {
        OrgDepartment d = requireDept(institutionId, id);
        long children = deptMapper.selectCount(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getParentId, id));
        if (children > 0) {
            throw BizException.badRequest("该部门下仍有 " + children + " 个子部门，请先迁移或删除子部门");
        }
        long members = memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getDepartmentId, id));
        if (members > 0) {
            throw BizException.badRequest("该部门下仍有 " + members + " 名员工，请先调整员工归属");
        }
        deptMapper.deleteById(id);
        audit.record(d.getTenantId(), institutionId, actor, "DEPT_DELETE", "ORG_DEPARTMENT", id,
                "删除部门「" + d.getName() + "」", d, null);
        return Map.of("deleted", id);
    }

    private OrgDepartment requireDept(Long institutionId, Long id) {
        OrgDepartment d = deptMapper.selectById(id);
        if (d == null || !institutionId.equals(d.getInstitutionId())) {
            throw BizException.notFound("部门不存在或不属于本机构：" + id);
        }
        return d;
    }

    private void checkDeptCode(Long institutionId, String code, Long excludeId) {
        if (code == null) {
            return;
        }
        LambdaQueryWrapper<OrgDepartment> w = new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId)
                .eq(OrgDepartment::getCode, code);
        if (excludeId != null) {
            w.ne(OrgDepartment::getId, excludeId);
        }
        if (deptMapper.selectCount(w) > 0) {
            throw BizException.badRequest("机构内部门编码已存在：" + code);
        }
    }

    // ------------------------------------------------------------------ G2 员工管理

    public Map<String, Object> listMembers(Long institutionId, Long departmentId, String keyword,
                                           boolean includeSubDept, int page, int size) {
        LambdaQueryWrapper<OrgMember> w = new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId);
        if (departmentId != null && departmentId > 0) {
            if (includeSubDept) {
                OrgDepartment d = deptMapper.selectById(departmentId);
                List<Long> ids = new ArrayList<>();
                ids.add(departmentId);
                if (d != null && d.getPath() != null) {
                    ids.addAll(deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                                    .eq(OrgDepartment::getInstitutionId, institutionId)
                                    .likeRight(OrgDepartment::getPath, d.getPath()))
                            .stream().map(OrgDepartment::getId).collect(Collectors.toList()));
                }
                w.in(OrgMember::getDepartmentId, ids);
            } else {
                w.eq(OrgMember::getDepartmentId, departmentId);
            }
        }
        if (keyword != null && !keyword.isBlank()) {
            w.and(q -> q.like(OrgMember::getName, keyword)
                    .or().like(OrgMember::getEmployeeNo, keyword)
                    .or().like(OrgMember::getMobile, keyword));
        }
        long total = memberMapper.selectCount(w);
        int p = Math.max(1, page);
        int s = Math.max(1, Math.min(size, 200));
        List<OrgMember> rows = memberMapper.selectList(w
                .orderByAsc(OrgMember::getDepartmentId).orderByAsc(OrgMember::getId)
                .last("limit " + ((p - 1) * s) + "," + s));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", total);
        out.put("page", p);
        out.put("size", s);
        out.put("items", rows);
        return out;
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> createMember(Long institutionId, AuthUser actor, Map<String, Object> body) {
        String name = Vals.require(body, "name", "姓名");
        Long deptId = Vals.lng(body, "departmentId", 0L);
        if (deptId != null && deptId > 0) {
            requireDept(institutionId, deptId);
        }
        String username = Vals.str(body, "username");
        Map<String, Object> target = accounts.resolveOrCreate(
                actor.getTenantId(), Vals.lngObj(body, "userId"), username, name,
                Vals.str(body, "mobile"), Vals.str(body, "email"), actor.getUserId());
        Long uid = AccountProvisioner.idOf(target);
        if (memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId)
                .eq(OrgMember::getUserId, uid)) > 0) {
            throw BizException.badRequest("该账号已是本机构成员：" + uid);
        }
        boolean isAdmin = Vals.bool(body, "isOrgAdmin", false);
        accounts.grantRole(uid, isAdmin ? OrgGuard.ROLE_ORG_ADMIN : OrgGuard.ROLE_MEMBER, actor.getUserId());

        OrgMember m = new OrgMember();
        m.setTenantId(actor.getTenantId() == null ? 0L : actor.getTenantId());
        m.setInstitutionId(institutionId);
        m.setDepartmentId(deptId == null ? 0L : deptId);
        m.setUserId(uid);
        m.setName(name);
        m.setMobile(Vals.str(body, "mobile"));
        m.setEmail(Vals.str(body, "email"));
        m.setEmployeeNo(Vals.str(body, "employeeNo"));
        m.setJobTitle(Vals.str(body, "jobTitle"));
        m.setIsOrgAdmin(isAdmin);
        m.setStatus(OrgMember.STATUS_ACTIVE);
        m.setJoinedAt(Vals.date(body, "joinedAt") == null ? LocalDate.now() : Vals.date(body, "joinedAt"));
        m.setCreatedAt(LocalDateTime.now());
        m.setCreatedBy(actor.getUserId());
        memberMapper.insert(m);

        audit.record(m.getTenantId(), institutionId, actor, "MEMBER_CREATE", "ORG_MEMBER", m.getId(),
                "新增员工「" + name + "」", null, m);
        return view(m);
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateMember(Long institutionId, Long id, AuthUser actor,
                                            Map<String, Object> body) {
        OrgMember m = requireMember(institutionId, id);
        OrgMember before = copy(m);
        if (Vals.str(body, "name") != null) {
            m.setName(Vals.str(body, "name"));
        }
        if (body != null && body.containsKey("departmentId")) {
            Long deptId = Vals.lng(body, "departmentId", 0L);
            if (deptId != null && deptId > 0) {
                requireDept(institutionId, deptId);
            }
            m.setDepartmentId(deptId == null ? 0L : deptId);
        }
        if (body != null && body.containsKey("mobile")) {
            m.setMobile(Vals.str(body, "mobile"));
        }
        if (body != null && body.containsKey("email")) {
            m.setEmail(Vals.str(body, "email"));
        }
        if (body != null && body.containsKey("employeeNo")) {
            m.setEmployeeNo(Vals.str(body, "employeeNo"));
        }
        if (body != null && body.containsKey("jobTitle")) {
            m.setJobTitle(Vals.str(body, "jobTitle"));
        }
        if (Vals.str(body, "status") != null) {
            m.setStatus(Vals.str(body, "status"));
        }
        if (body != null && body.containsKey("isOrgAdmin")) {
            boolean isAdmin = Vals.bool(body, "isOrgAdmin", false);
            if (isAdmin && !Boolean.TRUE.equals(m.getIsOrgAdmin())) {
                accounts.grantRole(m.getUserId(), OrgGuard.ROLE_ORG_ADMIN, actor.getUserId());
            } else if (!isAdmin && Boolean.TRUE.equals(m.getIsOrgAdmin())) {
                accounts.revokeRole(m.getUserId(), OrgGuard.ROLE_ORG_ADMIN);
            }
            m.setIsOrgAdmin(isAdmin);
        }
        m.setUpdatedAt(LocalDateTime.now());
        memberMapper.updateById(m);

        audit.record(m.getTenantId(), institutionId, actor, "MEMBER_UPDATE", "ORG_MEMBER", id,
                "编辑员工「" + m.getName() + "」", before, m);
        return view(m);
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> deleteMember(Long institutionId, Long id, AuthUser actor) {
        OrgMember m = requireMember(institutionId, id);
        if (Boolean.TRUE.equals(m.getIsOrgAdmin())) {
            throw BizException.badRequest("企业管理员不可直接删除，请先在机构管理页完成管理员交接（FR-B2）");
        }
        memberMapper.deleteById(id);
        accounts.revokeRole(m.getUserId(), OrgGuard.ROLE_MEMBER);
        audit.record(m.getTenantId(), institutionId, actor, "MEMBER_DELETE", "ORG_MEMBER", id,
                "移除员工「" + m.getName() + "」", m, null);
        return Map.of("deleted", id);
    }

    private OrgMember requireMember(Long institutionId, Long id) {
        OrgMember m = memberMapper.selectById(id);
        if (m == null || !institutionId.equals(m.getInstitutionId())) {
            throw BizException.notFound("员工不存在或不属于本机构：" + id);
        }
        return m;
    }

    // ------------------------------------------------------------------ G3 批量导入

    /**
     * 批量导入员工。每行独立事务语义（逐行 try/catch），失败行逐条返回原因，
     * 满足验收门禁「批量导入 500 名员工成功率 ≥ 99%」的可观测性要求。
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> importMembers(Long institutionId, AuthUser actor, List<Map<String, Object>> rows) {
        if (rows == null || rows.isEmpty()) {
            throw BizException.badRequest("导入名单为空");
        }
        if (rows.size() > 2000) {
            throw BizException.badRequest("单次导入不得超过 2000 行");
        }
        // 部门编码 / 名称 → id 索引，避免逐行查库
        Map<String, Long> deptIndex = new LinkedHashMap<>();
        for (OrgDepartment d : deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId))) {
            if (d.getCode() != null) {
                deptIndex.put(d.getCode(), d.getId());
            }
            deptIndex.putIfAbsent(d.getName(), d.getId());
        }
        // 已存在成员（按姓名 + 工号判重）
        Map<String, OrgMember> exists = new LinkedHashMap<>();
        for (OrgMember m : memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId))) {
            exists.put(key(m.getName(), m.getEmployeeNo()), m);
        }

        List<Map<String, Object>> failed = new ArrayList<>();
        int success = 0;
        int line = 0;
        for (Map<String, Object> row : rows) {
            line++;
            String rowName = Vals.str(row, "name");
            try {
                if (rowName == null) {
                    throw BizException.badRequest("缺少姓名");
                }
                String empNo = Vals.str(row, "employeeNo");
                if (exists.containsKey(key(rowName, empNo))) {
                    throw BizException.badRequest("名单内已存在同名同工号记录");
                }
                Long deptId = 0L;
                String deptCode = Vals.str(row, "departmentCode");
                String deptName = Vals.str(row, "departmentName");
                if (deptCode != null) {
                    deptId = deptIndex.get(deptCode);
                    if (deptId == null) {
                        throw BizException.badRequest("部门编码不存在：" + deptCode);
                    }
                } else if (deptName != null) {
                    deptId = deptIndex.get(deptName);
                    if (deptId == null) {
                        throw BizException.badRequest("部门名称不存在：" + deptName);
                    }
                }

                String username = Vals.str(row, "username");
                String mobile = Vals.str(row, "mobile");
                Map<String, Object> target = accounts.resolveOrCreate(actor.getTenantId(), null,
                        username == null ? ("u" + System.nanoTime() % 100000000L + line) : username,
                        rowName, mobile, Vals.str(row, "email"), actor.getUserId());
                Long uid = AccountProvisioner.idOf(target);
                if (memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                        .eq(OrgMember::getInstitutionId, institutionId)
                        .eq(OrgMember::getUserId, uid)) > 0) {
                    throw BizException.badRequest("该账号已是本机构成员");
                }
                accounts.grantRole(uid, OrgGuard.ROLE_MEMBER, actor.getUserId());

                OrgMember m = new OrgMember();
                m.setTenantId(actor.getTenantId() == null ? 0L : actor.getTenantId());
                m.setInstitutionId(institutionId);
                m.setDepartmentId(deptId);
                m.setUserId(uid);
                m.setName(rowName);
                m.setMobile(mobile);
                m.setEmail(Vals.str(row, "email"));
                m.setEmployeeNo(empNo);
                m.setJobTitle(Vals.str(row, "jobTitle"));
                m.setIsOrgAdmin(false);
                m.setStatus(OrgMember.STATUS_ACTIVE);
                m.setJoinedAt(Vals.date(row, "joinedAt") == null ? LocalDate.now() : Vals.date(row, "joinedAt"));
                m.setCreatedAt(LocalDateTime.now());
                m.setCreatedBy(actor.getUserId());
                memberMapper.insert(m);
                exists.put(key(rowName, empNo), m);
                success++;
            } catch (Exception e) {
                Map<String, Object> f = new LinkedHashMap<>();
                f.put("row", line);
                f.put("name", rowName);
                f.put("reason", e instanceof BizException ? e.getMessage() : "导入失败：" + e.getMessage());
                failed.add(f);
            }
        }

        audit.record(actor.getTenantId(), institutionId, actor,
                "MEMBER_IMPORT", "ORG_MEMBER", institutionId,
                "批量导入员工：成功 " + success + " / 共 " + rows.size() + "（失败 " + failed.size() + "）",
                null, Map.of("success", success, "failed", failed.size()));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", rows.size());
        out.put("success", success);
        out.put("failedCount", failed.size());
        out.put("successRate", rows.isEmpty() ? 0d : Math.round(success * 10000.0 / rows.size()) / 100.0);
        out.put("failed", failed);
        return out;
    }

    private static String key(String name, String empNo) {
        return (name == null ? "" : name) + "::" + (empNo == null ? "" : empNo);
    }

    // ------------------------------------------------------------------ 视图

    private Map<String, Object> view(OrgDepartment d) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", d.getId());
        m.put("institutionId", d.getInstitutionId());
        m.put("parentId", d.getParentId());
        m.put("name", d.getName());
        m.put("code", d.getCode());
        m.put("level", d.getLevel());
        m.put("path", d.getPath());
        m.put("leaderUserId", d.getLeaderUserId());
        m.put("leaderName", d.getLeaderName());
        m.put("sort", d.getSort());
        m.put("status", d.getStatus());
        return m;
    }

    private Map<String, Object> view(OrgMember m) {
        Map<String, Object> o = new LinkedHashMap<>();
        o.put("id", m.getId());
        o.put("institutionId", m.getInstitutionId());
        o.put("departmentId", m.getDepartmentId());
        o.put("userId", m.getUserId());
        o.put("name", m.getName());
        o.put("mobile", m.getMobile());
        o.put("email", m.getEmail());
        o.put("employeeNo", m.getEmployeeNo());
        o.put("jobTitle", m.getJobTitle());
        o.put("isOrgAdmin", m.getIsOrgAdmin());
        o.put("status", m.getStatus());
        o.put("joinedAt", m.getJoinedAt() == null ? null : m.getJoinedAt().toString());
        return o;
    }

    private static OrgDepartment copy(OrgDepartment d) {
        OrgDepartment c = new OrgDepartment();
        c.setId(d.getId());
        c.setTenantId(d.getTenantId());
        c.setInstitutionId(d.getInstitutionId());
        c.setParentId(d.getParentId());
        c.setName(d.getName());
        c.setCode(d.getCode());
        c.setLevel(d.getLevel());
        c.setPath(d.getPath());
        c.setLeaderUserId(d.getLeaderUserId());
        c.setLeaderName(d.getLeaderName());
        c.setSort(d.getSort());
        c.setStatus(d.getStatus());
        return c;
    }

    private static OrgMember copy(OrgMember m) {
        OrgMember c = new OrgMember();
        c.setId(m.getId());
        c.setTenantId(m.getTenantId());
        c.setInstitutionId(m.getInstitutionId());
        c.setDepartmentId(m.getDepartmentId());
        c.setUserId(m.getUserId());
        c.setName(m.getName());
        c.setMobile(m.getMobile());
        c.setEmail(m.getEmail());
        c.setEmployeeNo(m.getEmployeeNo());
        c.setJobTitle(m.getJobTitle());
        c.setIsOrgAdmin(m.getIsOrgAdmin());
        c.setStatus(m.getStatus());
        c.setJoinedAt(m.getJoinedAt());
        return c;
    }
}
