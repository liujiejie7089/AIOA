package cn.aioa.project.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.entity.PmContextSource;
import cn.aioa.project.entity.PmFolder;
import cn.aioa.project.entity.PmProject;
import cn.aioa.project.entity.PmProjectWorker;
import cn.aioa.project.mapper.PmAiRefMapper;
import cn.aioa.project.mapper.PmContextSourceMapper;
import cn.aioa.project.mapper.PmFolderMapper;
import cn.aioa.project.mapper.PmProjectWorkerMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 项目数字人分配 + 项目上下文控制（PM「数字人」批次，V74 建表 / V76 补权限码）。
 *
 * <p>设计依据 {@code docs/43 §5}。用户关键词：「分配项目数字人（后台上传，网上搜索,政策）」
 * 「项目上下文控制」。</p>
 *
 * <p><b>复用而非重造</b>：数字人 = 既有「数字员工」（{@code agent_worker}）。本服务只负责
 * 「把已存在的数字员工挂到项目上」与「维护该项目可用的上下文来源」，**绝不新建第二套数字人**
 * （见 docs/43 §5.1、A3）。读 {@code agent_worker} 走窄接口 {@link PmAiRefMapper}，只读、不改列。</p>
 *
 * <p><b>权限</b>：读写都先过 {@code PmProjectService.requireVisible}（数据范围唯一判定点）；
 * 写操作额外要求「可管理项目」或持有 {@code pm:ai:manage}。</p>
 *
 * <p><b>不级联删除的取舍</b>：把某数字员工从项目移除（{@link #unassignWorker}）时，
 * **会**一并软删「仅属于该数字员工」的上下文来源（{@code worker_id=该员工}）——否则会永久留下
 * 无主配置；而**项目级默认上下文**（{@code worker_id=0}）不受影响。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PmDigitalWorkerService {

    private static final ObjectMapper JSON = new ObjectMapper();

    /** 上下文来源类型 → 中文名（展示用，单一入口）。 */
    private static final Map<String, String> TYPE_LABELS = Map.of(
            PmContextSource.SOURCE_UPLOAD, "后台上传",
            PmContextSource.SOURCE_WEB_SEARCH, "网上搜索",
            PmContextSource.SOURCE_POLICY, "政策");

    /** 网上搜索默认返回条数。 */
    private static final int WEB_DEFAULT_MAX_RESULTS = 10;

    private final PmProjectWorkerMapper workerMapper;
    private final PmContextSourceMapper contextMapper;
    private final PmAiRefMapper aiRefMapper;
    private final PmFolderMapper folderMapper;
    private final PmProjectService projectService;
    private final OrgGuard guard;

    // ======================================================================
    // 数字员工分配
    // ======================================================================

    /** 项目已分配的数字员工 + 可分配候选。 */
    public Map<String, Object> workers(AuthUser user, Long projectId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        Long tenantId = p.getTenantId();

        List<PmProjectWorker> rows = workerMapper.selectList(new LambdaQueryWrapper<PmProjectWorker>()
                .eq(PmProjectWorker::getTenantId, tenantId)
                .eq(PmProjectWorker::getProjectId, projectId)
                .orderByAsc(PmProjectWorker::getId));

        List<Map<String, Object>> items = new ArrayList<>();
        Set<Long> assigned = new LinkedHashSet<>();
        for (PmProjectWorker r : rows) {
            assigned.add(r.getWorkerId());
            items.add(workerView(tenantId, r));
        }

        List<Map<String, Object>> candidates = new ArrayList<>();
        for (Map<String, Object> w : aiRefMapper.listAssignableWorkers(tenantId, guard.resolveInstitutionId(user.getUserId()))) {
            Long wid = asLong(w.get("id"));
            if (wid == null || assigned.contains(wid)) {
                continue;
            }
            Map<String, Object> c = new LinkedHashMap<>();
            c.put("workerId", wid);
            c.put("name", str(w.get("name")));
            c.put("workerType", str(w.get("worker_type")));
            c.put("status", str(w.get("status")));
            candidates.add(c);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("canManage", canWrite(user, p));
        out.put("items", items);
        out.put("candidates", candidates);
        return out;
    }

    /** 分配一个既有数字员工到本项目（幂等键：project+worker）。 */
    @Transactional
    public Map<String, Object> assignWorker(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        Long tenantId = p.getTenantId();

        Long workerId = asLong(body.get("workerId"));
        if (workerId == null) {
            throw BizException.badRequest("必须指定 workerId（既有数字员工）");
        }
        if (aiRefMapper.findWorker(tenantId, workerId) == null) {
            throw BizException.badRequest("数字员工不存在、已删除或不属于本租户：" + workerId);
        }
        Long dup = workerMapper.selectCount(new LambdaQueryWrapper<PmProjectWorker>()
                .eq(PmProjectWorker::getTenantId, tenantId)
                .eq(PmProjectWorker::getProjectId, projectId)
                .eq(PmProjectWorker::getWorkerId, workerId));
        if (dup != null && dup > 0) {
            throw new BizException(409, "该数字员工已分配到本项目，请勿重复分配");
        }

        PmProjectWorker r = new PmProjectWorker();
        r.setTenantId(tenantId);
        r.setProjectId(projectId);
        r.setWorkerId(workerId);
        r.setAssignRole(str(body.get("assignRole")).trim());
        r.setEnabled(1);
        r.setAssignedBy(user.getUserId());
        r.setCreatedAt(LocalDateTime.now());
        workerMapper.insert(r);
        return workerView(tenantId, r);
    }

    /** 更新分配的用途说明 / 启停（不改 workerId —— 换人请先移除再分配）。 */
    @Transactional
    public Map<String, Object> updateWorker(AuthUser user, Long projectId, Long id, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmProjectWorker r = requireAssignment(p.getTenantId(), projectId, id);

        if (body.containsKey("assignRole")) {
            r.setAssignRole(str(body.get("assignRole")).trim());
        }
        if (body.containsKey("enabled")) {
            r.setEnabled(asBool(body.get("enabled")) ? 1 : 0);
        }
        r.setUpdatedAt(LocalDateTime.now());
        workerMapper.updateById(r);
        return workerView(p.getTenantId(), r);
    }

    /** 从项目移除数字员工；一并软删「仅属于该员工」的上下文来源（项目级默认上下文不受影响）。 */
    @Transactional
    public Map<String, Object> unassignWorker(AuthUser user, Long projectId, Long id) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmProjectWorker r = requireAssignment(p.getTenantId(), projectId, id);

        Long removedSources = contextMapper.selectCount(new LambdaQueryWrapper<PmContextSource>()
                .eq(PmContextSource::getTenantId, p.getTenantId())
                .eq(PmContextSource::getProjectId, projectId)
                .eq(PmContextSource::getWorkerId, r.getWorkerId()));
        if (removedSources != null && removedSources > 0) {
            contextMapper.delete(new LambdaQueryWrapper<PmContextSource>()
                    .eq(PmContextSource::getTenantId, p.getTenantId())
                    .eq(PmContextSource::getProjectId, projectId)
                    .eq(PmContextSource::getWorkerId, r.getWorkerId()));
        }
        workerMapper.deleteById(r.getId());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("workerId", r.getWorkerId());
        out.put("removedContextSources", removedSources == null ? 0 : removedSources);
        return out;
    }

    private PmProjectWorker requireAssignment(Long tenantId, Long projectId, Long id) {
        PmProjectWorker r = workerMapper.selectById(id);
        if (r == null || !Objects.equals(r.getTenantId(), tenantId)
                || !Objects.equals(r.getProjectId(), projectId)) {
            throw BizException.notFound("分配记录不存在");
        }
        return r;
    }

    private Map<String, Object> workerView(Long tenantId, PmProjectWorker r) {
        Map<String, Object> w = aiRefMapper.findWorker(tenantId, r.getWorkerId());
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", r.getId());
        m.put("workerId", r.getWorkerId());
        m.put("name", w == null ? null : str(w.get("name")));
        m.put("workerType", w == null ? null : str(w.get("worker_type")));
        m.put("status", w == null ? null : str(w.get("status")));
        // 数字员工已被删（不在候选里）时，界面要能显示「已移除」而不是空白
        m.put("workerMissing", w == null);
        m.put("assignRole", r.getAssignRole());
        m.put("enabled", r.getEnabled() != null && r.getEnabled() == 1);
        m.put("assignedBy", r.getAssignedBy());
        m.put("createdAt", r.getCreatedAt());
        return m;
    }

    // ======================================================================
    // 上下文来源
    // ======================================================================

    /** 项目上下文来源清单 + 可选的数字员工分组信息。 */
    public Map<String, Object> contextSources(AuthUser user, Long projectId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        Long tenantId = p.getTenantId();

        List<PmContextSource> rows = contextMapper.selectList(new LambdaQueryWrapper<PmContextSource>()
                .eq(PmContextSource::getTenantId, tenantId)
                .eq(PmContextSource::getProjectId, projectId)
                .orderByAsc(PmContextSource::getSourceType).orderByAsc(PmContextSource::getId));

        List<Map<String, Object>> items = new ArrayList<>();
        for (PmContextSource s : rows) {
            items.add(contextView(tenantId, s));
        }

        List<Map<String, Object>> workers = new ArrayList<>();
        for (PmProjectWorker r : workerMapper.selectList(new LambdaQueryWrapper<PmProjectWorker>()
                .eq(PmProjectWorker::getTenantId, tenantId)
                .eq(PmProjectWorker::getProjectId, projectId)
                .orderByAsc(PmProjectWorker::getId))) {
            Map<String, Object> w = aiRefMapper.findWorker(tenantId, r.getWorkerId());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("workerId", r.getWorkerId());
            m.put("name", w == null ? ("#已移除#" + r.getWorkerId()) : str(w.get("name")));
            m.put("enabled", r.getEnabled() != null && r.getEnabled() == 1);
            workers.add(m);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("canManage", canWrite(user, p));
        out.put("items", items);
        out.put("workers", workers);
        out.put("types", typeOptions());
        return out;
    }

    /** 新增一个上下文来源（三类之一）。 */
    @Transactional
    public Map<String, Object> createContextSource(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        Long tenantId = p.getTenantId();

        String sourceType = str(body.get("sourceType")).trim().toUpperCase();
        if (!TYPE_LABELS.containsKey(sourceType)) {
            throw BizException.badRequest("未知上下文来源类型：" + sourceType + "（仅支持 UPLOAD/WEB_SEARCH/POLICY）");
        }
        Long workerId = body.get("workerId") == null
                ? PmContextSource.WORKER_DEFAULT : asLong(body.get("workerId"));
        if (workerId == null) {
            workerId = PmContextSource.WORKER_DEFAULT;
        }
        requireAssignedWorker(tenantId, projectId, workerId);

        PmContextSource s = new PmContextSource();
        s.setTenantId(tenantId);
        s.setProjectId(projectId);
        s.setWorkerId(workerId);
        s.setSourceType(sourceType);
        s.setEnabled(1);
        s.setCreatedBy(user.getUserId());
        s.setCreatedAt(LocalDateTime.now());

        String name = str(body.get("name")).trim();
        switch (sourceType) {
            case PmContextSource.SOURCE_UPLOAD -> {
                s.setFolderId(asLong(body.get("folderId")));
                s.setFileId(asLong(body.get("fileId")));
                s.setName(name.isEmpty() ? resolveUploadName(tenantId, projectId, s) : name);
            }
            case PmContextSource.SOURCE_WEB_SEARCH -> {
                s.setConfig(normalizeWebConfig(body.get("config")));
                s.setName(name.isEmpty() ? defaultWebName(s.getConfig()) : name);
            }
            case PmContextSource.SOURCE_POLICY -> {
                s.setKbDocumentId(asLong(body.get("kbDocumentId")));
                s.setName(name.isEmpty() ? resolvePolicyName(tenantId, s) : name);
            }
            default -> throw BizException.badRequest("未知上下文来源类型：" + sourceType);
        }
        contextMapper.insert(s);
        return contextView(tenantId, s);
    }

    /** 更新上下文来源：名称 / 启停 / 目标 / 归属数字员工（都需重过类型校验）。 */
    @Transactional
    public Map<String, Object> updateContextSource(AuthUser user, Long projectId, Long id, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        Long tenantId = p.getTenantId();
        PmContextSource s = requireContextSource(tenantId, projectId, id);

        if (body.containsKey("workerId")) {
            Long workerId = asLong(body.get("workerId"));
            if (workerId == null) {
                workerId = PmContextSource.WORKER_DEFAULT;
            }
            requireAssignedWorker(tenantId, projectId, workerId);
            s.setWorkerId(workerId);
        }
        if (body.containsKey("enabled")) {
            s.setEnabled(asBool(body.get("enabled")) ? 1 : 0);
        }
        // 目标字段：只有该类型允许的才接受，且改后仍需满足该类型的不变量
        switch (s.getSourceType()) {
            case PmContextSource.SOURCE_UPLOAD -> {
                if (body.containsKey("folderId")) {
                    s.setFolderId(asLong(body.get("folderId")));
                }
                if (body.containsKey("fileId")) {
                    s.setFileId(asLong(body.get("fileId")));
                }
                if (body.containsKey("name") || body.containsKey("folderId") || body.containsKey("fileId")) {
                    String name = str(body.get("name")).trim();
                    s.setName(name.isEmpty() ? resolveUploadName(tenantId, projectId, s) : name);
                }
            }
            case PmContextSource.SOURCE_WEB_SEARCH -> {
                if (body.containsKey("config")) {
                    s.setConfig(normalizeWebConfig(body.get("config")));
                }
                if (body.containsKey("name")) {
                    String name = str(body.get("name")).trim();
                    s.setName(name.isEmpty() ? defaultWebName(s.getConfig()) : name);
                }
            }
            case PmContextSource.SOURCE_POLICY -> {
                if (body.containsKey("kbDocumentId")) {
                    s.setKbDocumentId(asLong(body.get("kbDocumentId")));
                }
                if (body.containsKey("name") || body.containsKey("kbDocumentId")) {
                    String name = str(body.get("name")).trim();
                    s.setName(name.isEmpty() ? resolvePolicyName(tenantId, s) : name);
                }
            }
            default -> throw BizException.badRequest("未知上下文来源类型：" + s.getSourceType());
        }
        s.setUpdatedAt(LocalDateTime.now());
        contextMapper.updateById(s);
        return contextView(tenantId, s);
    }

    /** 删除上下文来源（软删）。 */
    @Transactional
    public void deleteContextSource(AuthUser user, Long projectId, Long id) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmContextSource s = requireContextSource(p.getTenantId(), projectId, id);
        contextMapper.deleteById(s.getId());
    }

    // ======================================================================
    // 上下文装配（「项目上下文控制」的生效视图）
    // ======================================================================

    /**
     * 组装某数字员工在本项目**实际生效**的上下文来源（{@code enabled=1}）：
     * 项目级默认（{@code worker_id=0}）+ 该员工专属。
     *
     * <p>这是 `docs/43 §5.3` 所述下发链路（{@code RunService.buildScope}）的**数据出口**：
     * 下发链路尚未接线（属跨域改动，见下方说明），但「现在到底会给数字人喂什么」
     * 必须可查可验——否则「项目上下文控制」只是一个无法观察的开关。</p>
     *
     * <p>{@code workerId} 省略时只回项目级默认（查看「项目公共上下文」）。</p>
     */
    public Map<String, Object> effectiveScope(AuthUser user, Long projectId, Long workerId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        Long tenantId = p.getTenantId();
        long wid = workerId == null ? PmContextSource.WORKER_DEFAULT : workerId;

        List<Map<String, Object>> projectDefault = new ArrayList<>();
        List<Map<String, Object>> workerSpecific = new ArrayList<>();
        for (PmContextSource s : contextMapper.selectList(new LambdaQueryWrapper<PmContextSource>()
                .eq(PmContextSource::getTenantId, tenantId)
                .eq(PmContextSource::getProjectId, projectId)
                .eq(PmContextSource::getEnabled, 1)
                .orderByAsc(PmContextSource::getId))) {
            if (s.isProjectDefault()) {
                projectDefault.add(contextView(tenantId, s));
            } else if (wid != PmContextSource.WORKER_DEFAULT && Objects.equals(s.getWorkerId(), wid)) {
                workerSpecific.add(contextView(tenantId, s));
            }
        }
        List<Map<String, Object>> effective = new ArrayList<>(projectDefault);
        effective.addAll(workerSpecific);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectId", projectId);
        out.put("workerId", wid);
        out.put("projectDefault", projectDefault);
        out.put("workerSpecific", workerSpecific);
        out.put("effective", effective);
        out.put("effectiveCount", effective.size());
        return out;
    }

    // ======================================================================
    // 类型校验 / 视图 / 权限
    // ======================================================================

    private List<Map<String, Object>> typeOptions() {
        List<Map<String, Object>> list = new ArrayList<>();
        for (Map.Entry<String, String> e : TYPE_LABELS.entrySet()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("value", e.getKey());
            m.put("label", e.getValue());
            list.add(m);
        }
        return list;
    }

    private void requireAssignedWorker(Long tenantId, Long projectId, long workerId) {
        if (workerId == PmContextSource.WORKER_DEFAULT) {
            return;
        }
        Long n = workerMapper.selectCount(new LambdaQueryWrapper<PmProjectWorker>()
                .eq(PmProjectWorker::getTenantId, tenantId)
                .eq(PmProjectWorker::getProjectId, projectId)
                .eq(PmProjectWorker::getWorkerId, workerId));
        if (n == null || n == 0) {
            throw BizException.badRequest("指定数字员工未分配到本项目：" + workerId + "（请先分配，或留空为项目级默认）");
        }
    }

    /** UPLOAD：至少要有目录或文件之一；并回填显示名。 */
    private String resolveUploadName(Long tenantId, Long projectId, PmContextSource s) {
        if (s.getFolderId() != null) {
            PmFolder f = folderMapper.selectById(s.getFolderId());
            if (f == null || !Objects.equals(f.getTenantId(), tenantId)
                    || !Objects.equals(f.getProjectId(), projectId)
                    || !PmFolder.SCOPE_PROJECT.equals(f.getScope())) {
                throw BizException.badRequest("目录不存在或不属于本项目：" + s.getFolderId());
            }
            return "目录：" + f.getName();
        }
        if (s.getFileId() != null) {
            String n = aiRefMapper.fileOriginalName(tenantId, s.getFileId());
            if (n == null) {
                throw BizException.badRequest("文件不存在或不属于本租户：" + s.getFileId());
            }
            return "文件：" + n;
        }
        throw BizException.badRequest("后台上传来源必须提供 folderId（整目录）或 fileId（单文件）之一");
    }

    /** POLICY：政策文档必填且必须存在；回填显示名。 */
    private String resolvePolicyName(Long tenantId, PmContextSource s) {
        if (s.getKbDocumentId() == null) {
            throw BizException.badRequest("政策来源必须提供 kbDocumentId（政策知识库文档）");
        }
        String n = aiRefMapper.kbDocName(tenantId, s.getKbDocumentId());
        if (n == null) {
            throw BizException.badRequest("政策文档不存在或不属于本租户：" + s.getKbDocumentId());
        }
        return "政策：" + n;
    }

    /** WEB_SEARCH：keywords 必填；归一化为 {keywords,domains,maxResults}。 */
    @SuppressWarnings("unchecked")
    private String normalizeWebConfig(Object raw) {
        if (raw == null) {
            throw BizException.badRequest("网上搜索来源必须提供 config");
        }
        Map<String, Object> m;
        if (raw instanceof Map<?, ?> mm) {
            m = (Map<String, Object>) mm;
        } else {
            String s = String.valueOf(raw).trim();
            if (s.isEmpty()) {
                throw BizException.badRequest("网上搜索来源必须提供 config");
            }
            try {
                m = JSON.readValue(s, Map.class);
            } catch (Exception e) {
                throw BizException.badRequest("config 不是合法 JSON：" + e.getMessage());
            }
        }
        List<String> keywords = new ArrayList<>();
        Object kw = m.get("keywords");
        if (kw instanceof List<?> l) {
            for (Object o : l) {
                String k = str(o).trim();
                if (!k.isEmpty()) {
                    keywords.add(k);
                }
            }
        }
        if (keywords.isEmpty()) {
            throw BizException.badRequest("config.keywords 至少需要 1 个关键词");
        }
        List<String> domains = new ArrayList<>();
        Object dm = m.get("domains");
        if (dm instanceof List<?> l) {
            for (Object o : l) {
                String k = str(o).trim();
                if (!k.isEmpty()) {
                    domains.add(k);
                }
            }
        }
        int max = WEB_DEFAULT_MAX_RESULTS;
        Object mr = m.get("maxResults");
        if (mr != null) {
            Long v = asLong(mr);
            if (v != null && v > 0) {
                max = (int) Math.min(v, 100L);
            }
        }
        Map<String, Object> normalized = new LinkedHashMap<>();
        normalized.put("keywords", keywords);
        normalized.put("domains", domains);
        normalized.put("maxResults", max);
        try {
            return JSON.writeValueAsString(normalized);
        } catch (Exception e) {
            throw BizException.badRequest("config 序列化失败：" + e.getMessage());
        }
    }

    private String defaultWebName(String config) {
        try {
            Map<?, ?> m = JSON.readValue(config, Map.class);
            Object kw = m.get("keywords");
            if (kw instanceof List<?> l && !l.isEmpty()) {
                List<String> parts = new ArrayList<>();
                for (Object o : l) {
                    parts.add(str(o));
                }
                return "网搜：" + String.join("、", parts);
            }
        } catch (Exception ignore) {
            // 名称兜底，不影响主流程
        }
        return "网上搜索";
    }

    private PmContextSource requireContextSource(Long tenantId, Long projectId, Long id) {
        PmContextSource s = contextMapper.selectById(id);
        if (s == null || !Objects.equals(s.getTenantId(), tenantId)
                || !Objects.equals(s.getProjectId(), projectId)) {
            throw BizException.notFound("上下文来源不存在");
        }
        return s;
    }

    private Map<String, Object> contextView(Long tenantId, PmContextSource s) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", s.getId());
        m.put("sourceType", s.getSourceType());
        m.put("typeLabel", TYPE_LABELS.getOrDefault(s.getSourceType(), s.getSourceType()));
        m.put("name", s.getName());
        m.put("workerId", s.getWorkerId());
        m.put("workerName", resolveWorkerName(tenantId, s.getWorkerId()));
        m.put("folderId", s.getFolderId());
        m.put("fileId", s.getFileId());
        m.put("kbDocumentId", s.getKbDocumentId());
        m.put("config", s.getConfig());
        m.put("enabled", s.getEnabled() != null && s.getEnabled() == 1);
        m.put("createdBy", s.getCreatedBy());
        m.put("createdAt", s.getCreatedAt());
        return m;
    }

    private String resolveWorkerName(Long tenantId, Long workerId) {
        if (workerId == null || workerId == PmContextSource.WORKER_DEFAULT) {
            return "项目级（全体数字人）";
        }
        Map<String, Object> w = aiRefMapper.findWorker(tenantId, workerId);
        return w == null ? ("#已移除#" + workerId) : str(w.get("name"));
    }

    /** 能否维护本项目的数字人 / 上下文：可管理项目，或持有 {@code pm:ai:manage}。 */
    private boolean canWrite(AuthUser user, PmProject p) {
        return projectService.canManage(user, p) || PermissionCatalog.holds(user, PermissionCatalog.PM_AI_MANAGE);
    }

    private void requireWrite(AuthUser user, PmProject p) {
        if (!canWrite(user, p)) {
            throw BizException.forbidden("仅项目负责人/项目经理、机构管理员及以上，或数字人管理员可维护数字人分配与上下文");
        }
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static Long asLong(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof Number n) {
            return n.longValue();
        }
        String s = String.valueOf(o).trim();
        if (s.isEmpty()) {
            return null;
        }
        try {
            return Long.parseLong(s);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static boolean asBool(Object o) {
        if (o == null) {
            return false;
        }
        if (o instanceof Boolean b) {
            return b;
        }
        String s = String.valueOf(o).trim();
        return "1".equals(s) || "true".equalsIgnoreCase(s) || "yes".equalsIgnoreCase(s);
    }
}
