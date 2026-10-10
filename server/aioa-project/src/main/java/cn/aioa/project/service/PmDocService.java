package cn.aioa.project.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.entity.PmDocument;
import cn.aioa.project.entity.PmFolder;
import cn.aioa.project.entity.PmProject;
import cn.aioa.project.mapper.PmAiRefMapper;
import cn.aioa.project.mapper.PmDocumentMapper;
import cn.aioa.project.mapper.PmFolderMapper;
import cn.aioa.project.support.PmProjectStatus;
import cn.aioa.security.AuthUser;
import cn.aioa.security.PermissionCatalog;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 项目文档服务（PM 批次 3，V72）。
 *
 * <p>设计依据 {@code docs/40 §6.2/§7.2} + {@code docs/43}。用户关键词：
 * 「每个项目创建一个文档目录；所有文档（外部上传 + 大模型创建）」。</p>
 *
 * <p><b>两类文件夹同表</b>（{@code pm_folder.scope}）：</p>
 * <ul>
 *   <li>{@link PmFolder#SCOPE_ENTERPRISE} 企业级公共文件夹（跨项目，{@code project_id=0}）——
 *       进项目文档页时**只读挂载**，写操作提示去「企业文档」页维护；</li>
 *   <li>{@link PmFolder#SCOPE_PROJECT} 项目专属文件夹——挂在项目下，随项目软删级联（BR-07）。</li>
 * </ul>
 *
 * <p><b>每个项目都有一个根目录</b>：{@link #ensureProjectRoot} 幂等保证（新项目在
 * {@code PmProjectService.create} 时创建，历史项目在首次打开文档页时补齐）——
 * 用户看到的永远是「项目文档」这一层根，不需要手工建。</p>
 *
 * <p><b>权限</b>：读写都先过 {@code PmProjectService.requireVisible}（数据范围唯一判定点），
 * 写操作额外要求「可管理项目」或持有 {@code pm:doc:manage}（企业文档管理员）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PmDocService {

    /** 项目根目录的显示名。 */
    public static final String PROJECT_ROOT_NAME = "项目文档";
    /** 企业级公共文件夹的根（虚拟节点，不落库）在界面上的名字。 */
    public static final String ENTERPRISE_ROOT_LABEL = "企业级公共文件夹";

    private final PmFolderMapper folderMapper;
    private final PmDocumentMapper documentMapper;
    private final PmProjectService projectService;
    private final OrgGuard guard;
    /** 只读窄接口：查 {@code sys_file} 的真实字节数（{@code sizeBytes} 的事实源）。 */
    private final PmAiRefMapper aiRefMapper;

    // ======================================================================
    // 根目录
    // ======================================================================

    /**
     * 幂等确保某项目存在根目录，返回它。
     *
     * <p>唯一键含 {@code alive}（软删行从约束消失）⇒ 插入前必须先查活行，否则「删了目录再打开」
     * 会在唯一键上撞不上、却插出第二棵树。</p>
     */
    @Transactional
    public PmFolder ensureProjectRoot(Long tenantId, Long projectId, Long actorId) {
        PmFolder existing = findRoot(tenantId, projectId);
        if (existing != null) {
            return existing;
        }
        PmFolder f = new PmFolder();
        f.setTenantId(tenantId);
        f.setScope(PmFolder.SCOPE_PROJECT);
        f.setProjectId(projectId);
        f.setParentId(PmFolder.ROOT_PARENT);
        f.setName(PROJECT_ROOT_NAME);
        f.setStorageKind("LOCAL");
        f.setCreatedBy(actorId);
        f.setCreatedAt(LocalDateTime.now());
        try {
            folderMapper.insert(f);
        } catch (DuplicateKeyException e) {
            // 并发下另一个请求已建好 —— 回读即可（幂等语义）
            PmFolder again = findRoot(tenantId, projectId);
            if (again != null) {
                return again;
            }
            throw e;
        }
        f.setPath("/" + f.getId() + "/");
        folderMapper.updateById(f);
        return f;
    }

    private PmFolder findRoot(Long tenantId, Long projectId) {
        List<PmFolder> rows = folderMapper.selectList(new LambdaQueryWrapper<PmFolder>()
                .eq(PmFolder::getTenantId, tenantId)
                .eq(PmFolder::getScope, PmFolder.SCOPE_PROJECT)
                .eq(PmFolder::getProjectId, projectId)
                .eq(PmFolder::getParentId, PmFolder.ROOT_PARENT)
                .last("LIMIT 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    // ======================================================================
    // 读：树
    // ======================================================================

    /** 项目文档树 = 企业级公共（只读挂载）+ 项目专属（可写）。 */
    public Map<String, Object> tree(AuthUser user, Long projectId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        Long tenantId = p.getTenantId();
        // 首次打开时补齐根目录（历史项目也适用）
        ensureProjectRoot(tenantId, projectId, user.getUserId());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("canManage", canWrite(user, p));
        out.put("projectRootName", PROJECT_ROOT_NAME);
        out.put("enterpriseRootLabel", ENTERPRISE_ROOT_LABEL);

        out.put("enterprise", buildTree(tenantId, PmFolder.SCOPE_ENTERPRISE, 0L, true));
        out.put("project", buildTree(tenantId, PmFolder.SCOPE_PROJECT, projectId, false));
        return out;
    }

    /** 企业文档树（跨项目，供「企业文档」页使用）。 */
    public Map<String, Object> enterpriseTree(AuthUser user) {
        Long tenantId = guard.tenantId();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("scope", PmFolder.SCOPE_ENTERPRISE);
        out.put("canManage", PermissionCatalog.holds(user, PermissionCatalog.PM_DOC_MANAGE));
        out.put("roots", buildTree(tenantId, PmFolder.SCOPE_ENTERPRISE, 0L, false));
        return out;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> buildTree(Long tenantId, String scope, Long projectId, boolean readonly) {
        List<PmFolder> folders = folderMapper.selectList(new LambdaQueryWrapper<PmFolder>()
                .eq(PmFolder::getTenantId, tenantId)
                .eq(PmFolder::getScope, scope)
                .eq(PmFolder::getProjectId, projectId)
                .orderByAsc(PmFolder::getParentId).orderByAsc(PmFolder::getName));

        List<Long> folderIds = new ArrayList<>();
        folders.forEach(f -> folderIds.add(f.getId()));

        Map<Long, List<PmDocument>> docsByFolder = new LinkedHashMap<>();
        if (!folderIds.isEmpty()) {
            List<PmDocument> docs = documentMapper.selectList(new LambdaQueryWrapper<PmDocument>()
                    .in(PmDocument::getFolderId, folderIds)
                    .orderByDesc(PmDocument::getCreatedAt));
            docs.forEach(d -> docsByFolder.computeIfAbsent(d.getFolderId(), k -> new ArrayList<>()).add(d));
        }

        Map<Long, Map<String, Object>> nodes = new LinkedHashMap<>();
        for (PmFolder f : folders) {
            Map<String, Object> n = new LinkedHashMap<>();
            n.put("id", f.getId());
            n.put("name", f.getName());
            n.put("parentId", f.getParentId());
            n.put("scope", f.getScope());
            n.put("readonly", readonly);
            n.put("storageKind", f.getStorageKind());
            n.put("children", new ArrayList<Map<String, Object>>());
            List<PmDocument> ds = docsByFolder.getOrDefault(f.getId(), List.of());
            List<Map<String, Object>> dv = new ArrayList<>();
            ds.forEach(d -> dv.add(docView(d)));
            n.put("documents", dv);
            n.put("documentCount", dv.size());
            nodes.put(f.getId(), n);
        }
        List<Map<String, Object>> roots = new ArrayList<>();
        for (PmFolder f : folders) {
            Map<String, Object> node = nodes.get(f.getId());
            if (f.getParentId() != null && f.getParentId() != PmFolder.ROOT_PARENT && nodes.containsKey(f.getParentId())) {
                ((List<Map<String, Object>>) nodes.get(f.getParentId()).get("children")).add(node);
            } else {
                roots.add(node);
            }
        }
        return roots;
    }

    private Map<String, Object> docView(PmDocument d) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", d.getId());
        m.put("folderId", d.getFolderId());
        m.put("name", d.getName());
        m.put("fileId", d.getFileId());
        m.put("source", d.getSource());
        m.put("sizeBytes", d.getSizeBytes());
        m.put("version", d.getVersion());
        m.put("tags", d.getTags());
        m.put("uploadedBy", d.getUploadedBy());
        m.put("createdAt", d.getCreatedAt());
        return m;
    }

    /** 单文档详情（含 AI 正文）；前端预览用。 */
    public Map<String, Object> documentDetail(AuthUser user, Long projectId, Long docId) {
        PmDocument d = requireDocument(user, projectId, docId);
        Map<String, Object> m = docView(d);
        m.put("contentText", d.getContentText());
        return m;
    }

    // ======================================================================
    // 写：文件夹
    // ======================================================================

    @Transactional
    public Map<String, Object> createFolder(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        Long tenantId = p.getTenantId();

        String name = str(body.get("name")).trim();
        if (name.isEmpty()) {
            throw BizException.badRequest("文件夹名不能为空");
        }
        Long parentId = body.get("parentId") == null ? PmFolder.ROOT_PARENT : asLong(body.get("parentId"));
        PmFolder parent = null;
        if (parentId != PmFolder.ROOT_PARENT) {
            parent = folderMapper.selectById(parentId);
            if (parent == null || !Objects.equals(parent.getTenantId(), tenantId)
                    || !Objects.equals(parent.getProjectId(), projectId)
                    || !PmFolder.SCOPE_PROJECT.equals(parent.getScope())) {
                throw BizException.badRequest("父文件夹不存在或不属于本项目");
            }
        }

        // 软删行从唯一键消失 ⇒ 插入前先查活行（V71 约定）
        Long dup = folderMapper.selectCount(new LambdaQueryWrapper<PmFolder>()
                .eq(PmFolder::getTenantId, tenantId)
                .eq(PmFolder::getScope, PmFolder.SCOPE_PROJECT)
                .eq(PmFolder::getProjectId, projectId)
                .eq(PmFolder::getParentId, parentId)
                .eq(PmFolder::getName, name));
        if (dup != null && dup > 0) {
            throw new BizException(409, "同级下已存在同名文件夹");
        }

        PmFolder f = new PmFolder();
        f.setTenantId(tenantId);
        f.setScope(PmFolder.SCOPE_PROJECT);
        f.setProjectId(projectId);
        f.setParentId(parentId);
        f.setName(name);
        f.setStorageKind("LOCAL");
        f.setCreatedBy(user.getUserId());
        f.setCreatedAt(LocalDateTime.now());
        folderMapper.insert(f);
        f.setPath((parent == null ? "/" : parent.getPath()) + f.getId() + "/");
        folderMapper.updateById(f);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", f.getId());
        out.put("name", f.getName());
        out.put("parentId", f.getParentId());
        out.put("path", f.getPath());
        return out;
    }

    /** 删除文件夹（BR-08：只允许删空文件夹，无隐式递归删除）。 */
    @Transactional
    public void deleteFolder(AuthUser user, Long projectId, Long folderId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        Long tenantId = p.getTenantId();

        PmFolder f = folderMapper.selectById(folderId);
        if (f == null || !Objects.equals(f.getTenantId(), tenantId)
                || !Objects.equals(f.getProjectId(), projectId)) {
            throw BizException.notFound("文件夹不存在");
        }
        if (Objects.equals(f.getParentId(), PmFolder.ROOT_PARENT)) {
            throw BizException.badRequest("项目根目录不可删除");
        }

        Long childFolders = folderMapper.selectCount(new LambdaQueryWrapper<PmFolder>()
                .eq(PmFolder::getParentId, folderId));
        Long childDocs = documentMapper.selectCount(new LambdaQueryWrapper<PmDocument>()
                .eq(PmDocument::getFolderId, folderId));
        long sub = (childFolders == null ? 0 : childFolders) + (childDocs == null ? 0 : childDocs);
        if (sub > 0) {
            throw new BizException(409, "文件夹非空（子文件夹 " + (childFolders == null ? 0 : childFolders)
                    + " 个、文档 " + (childDocs == null ? 0 : childDocs) + " 份），请先清空");
        }
        folderMapper.deleteById(folderId);
    }

    // ======================================================================
    // 写：文档
    // ======================================================================

    /**
     * 登记一份文档到文件夹。
     *
     * <p>{@code source=UPLOAD}：调用方须先经 {@code POST /api/v1/files/upload} 拿到 {@code fileId}，
     * 此处只落索引（字节在 {@code sys_file}）。{@code source=AI}：正文由调用方（项目数字人生成流程）
     * 传入 {@code contentText}；两者共用同一张表、同一套版本规则。</p>
     */
    @Transactional
    public Map<String, Object> createDocument(AuthUser user, Long projectId, Map<String, Object> body) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        Long tenantId = p.getTenantId();

        Long folderId = asLong(body.get("folderId"));
        if (folderId == null) {
            throw BizException.badRequest("必须指定 folderId");
        }
        PmFolder folder = folderMapper.selectById(folderId);
        if (folder == null || !Objects.equals(folder.getTenantId(), tenantId)
                || !Objects.equals(folder.getProjectId(), projectId)
                || !PmFolder.SCOPE_PROJECT.equals(folder.getScope())) {
            throw BizException.badRequest("文件夹不存在或不属于本项目（企业级文档请在「企业文档」页维护）");
        }

        String source = str(body.get("source")).isEmpty() ? PmDocument.SOURCE_UPLOAD : str(body.get("source"));
        if (!PmDocument.SOURCE_UPLOAD.equals(source) && !PmDocument.SOURCE_AI.equals(source)) {
            throw BizException.badRequest("未知文档来源：" + source);
        }
        Long fileId = asLong(body.get("fileId"));
        String contentText = str(body.get("contentText"));
        if (PmDocument.SOURCE_UPLOAD.equals(source) && fileId == null) {
            throw BizException.badRequest("外部上传文档必须提供 fileId（先调用 /api/v1/files/upload）");
        }
        if (PmDocument.SOURCE_AI.equals(source) && contentText.isEmpty() && fileId == null) {
            throw BizException.badRequest("大模型创建的文档必须提供 contentText 或 fileId");
        }

        String name = str(body.get("name")).trim();
        if (name.isEmpty()) {
            name = "未命名文档";
        }
        // pm_document.name 是 VARCHAR(256)：超长会在 INSERT 时炸成 500，这里提前挡成 400。
        if (name.length() > 200) {
            throw BizException.badRequest("文档名称过长（最多 200 字，当前 " + name.length() + " 字）");
        }

        int version = nextVersion(folderId, name);

        // sizeBytes 的事实源：AI 创建 = 正文 UTF-8 字节数；外部上传 = sys_file 的真实字节数。
        //
        // ⚠ 切勿写成 `cond ? asLong(body.get("sizeBytes")) : (long) ...`：
        //   三元表达式要做「数值提升」，另一支是基本类型 long，会把这一支的包装类型 Long 一并拆箱；
        //   而上传路径 contentText 为空、前端也不传 sizeBytes ⇒ asLong(null) 返回 null ⇒
        //   NullPointerException ⇒ 接口回 500（2026-10-10 实测：管理端「上传文档」100% 失败）。
        //   改为赋给局部变量 Long，即可保留可空语义、不做拆箱。
        Long sizeBytes;
        if (PmDocument.SOURCE_AI.equals(source) && !contentText.isEmpty()) {
            sizeBytes = (long) contentText.getBytes(StandardCharsets.UTF_8).length;
        } else {
            sizeBytes = asLong(body.get("sizeBytes"));
            if (sizeBytes == null && fileId != null) {
                // 后端能自己查到就自己查 —— 不依赖调用方是否传 sizeBytes，避免两端各存一份而漂移。
                sizeBytes = aiRefMapper.fileSize(tenantId, fileId);
            }
        }

        PmDocument d = new PmDocument();
        d.setTenantId(tenantId);
        d.setFolderId(folderId);
        d.setProjectId(projectId);
        d.setName(name);
        d.setFileId(fileId);
        d.setSource(source);
        d.setContentText(contentText.isEmpty() ? null : contentText);
        d.setSizeBytes(sizeBytes);
        d.setVersion(version);
        d.setTags(str(body.get("tags")));
        d.setUploadedBy(user.getUserId());
        d.setCreatedAt(LocalDateTime.now());
        documentMapper.insert(d);
        return docView(d);
    }

    private int nextVersion(Long folderId, String name) {
        List<PmDocument> rows = documentMapper.selectList(new LambdaQueryWrapper<PmDocument>()
                .eq(PmDocument::getFolderId, folderId)
                .eq(PmDocument::getName, name)
                .orderByDesc(PmDocument::getVersion)
                .last("LIMIT 1"));
        return rows.isEmpty() ? 1 : rows.get(0).getVersion() + 1;
    }

    /** 删除文档索引（BR-07：不物理删 sys_file 字节，保留可追溯）。 */
    @Transactional
    public void deleteDocument(AuthUser user, Long projectId, Long docId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        requireWrite(user, p);
        PmDocument d = requireDocument(user, projectId, docId);
        documentMapper.deleteById(d.getId());
    }

    private PmDocument requireDocument(AuthUser user, Long projectId, Long docId) {
        PmProject p = projectService.requireVisible(user, projectId, false);
        PmDocument d = documentMapper.selectById(docId);
        if (d == null || !Objects.equals(d.getTenantId(), p.getTenantId())
                || !Objects.equals(d.getProjectId(), projectId)) {
            throw BizException.notFound("文档不存在");
        }
        return d;
    }

    // ======================================================================
    // 权限 / 工具
    // ======================================================================

    /** 能否在本项目写文档：可管理项目，或持有 {@code pm:doc:manage}（企业文档管理员）。 */
    private boolean canWrite(AuthUser user, PmProject p) {
        return projectService.canManage(user, p) || PermissionCatalog.holds(user, PermissionCatalog.PM_DOC_MANAGE);
    }

    /**
     * 写文档的统一闸门：**先判权限，再判项目状态**。
     *
     * <p>本服务的全部写动作（建文件夹 / 删文件夹 / 登记文档 / 删文档）都经此一处，
     * 故「项目只读终态（已结项 / 已归档）不得再写文档」也放在这里 ——
     * 逐个入口各写一遍必然漏掉一个。只读判定复用 {@link PmProjectStatus#isReadOnly}
     * （该类自述是「该判定的唯一决策点」，不允许各 service 自己写状态比较）。</p>
     */
    private void requireWrite(AuthUser user, PmProject p) {
        if (!canWrite(user, p)) {
            throw BizException.forbidden("仅项目负责人/项目经理、机构管理员及以上，或企业文档管理员可维护文档");
        }
        if (PmProjectStatus.isReadOnly(p.getStatus())) {
            throw BizException.badRequest("项目已"
                    + (PmProjectStatus.CLOSED.equals(p.getStatus()) ? "结项" : "归档")
                    + "，不能再维护文档");
        }
    }

    public static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    public static Long asLong(Object o) {
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
}
