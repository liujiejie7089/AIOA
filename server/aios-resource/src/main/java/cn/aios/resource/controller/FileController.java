package cn.aios.resource.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.entity.SysFile;
import cn.aios.resource.mapper.SysFileMapper;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.io.InputStream;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 通用文件上传（请假证明等附件）：
 *   POST /api/v1/files/upload  —— multipart 上传，返回 {id,name,url,size}
 *   GET  /api/v1/files/{id}    —— 下载/预览
 * 文件本体存本地目录（可配置 aios.upload.dir），元数据落 sys_file；
 * 后续替换为对象存储时仅改本类读写实现，调用方无需变动。
 */
@RestController
@RequestMapping("/api/v1/files")
@RequiredArgsConstructor
public class FileController {

    private final SysFileMapper fileMapper;

    @Value("${aios.upload.dir:./uploads}")
    private String uploadDir;

    /**
     * 上传体积上限（MB）—— 唯一数字来自配置 <b>aios.file.max-size-mb</b>，
     * 与 {@code spring.servlet.multipart.max-file-size} 是同一个键的引用
     * （见 application.yml 里 multipart 的占位符）。
     *
     * <p>历史缺陷（docs/44 §3.3-5）：这两个上限曾各写一份字面量 50MB，
     * 只改其中一处就会出现「容器已放行、应用层仍按旧值 400」的口径漂移。
     * 现在应用层不再持有数字，只负责给出可读文案。</p>
     */
    @Value("${aios.file.max-size-mb:50}")
    private long maxSizeMb;

    private Path root;

    @PostConstruct
    void init() {
        root = Paths.get(uploadDir).toAbsolutePath().normalize();
        try {
            Files.createDirectories(root);
        } catch (IOException e) {
            throw new IllegalStateException("创建上传目录失败：" + root, e);
        }
    }

    @PostMapping("/upload")
    public ApiResponse<Map<String, Object>> upload(@RequestParam("file") MultipartFile file) {
        AuthUser user = AuthUserContext.require();
        if (file == null || file.isEmpty()) {
            throw BizException.badRequest("请选择要上传的文件");
        }
        String original = file.getOriginalFilename();
        if (original == null || original.isBlank()) {
            throw BizException.badRequest("文件名无效");
        }
        if (file.getSize() > maxSizeMb * 1024 * 1024) {
            throw BizException.badRequest("文件超过 " + maxSizeMb + "MB 上限");
        }
        String ext = "";
        int dot = original.lastIndexOf('.');
        if (dot > 0) {
            ext = original.substring(dot).toLowerCase();
        }
        String stored = UUID.randomUUID() + ext;
        Path target = root.resolve(stored);
        try (InputStream in = file.getInputStream()) {
            Files.copy(in, target);
        } catch (IOException e) {
            throw BizException.badRequest("文件保存失败：" + e.getMessage());
        }
        SysFile rec = new SysFile();
        rec.setTenantId(user.getTenantId());
        rec.setUserId(user.getUserId());
        rec.setOriginalName(original);
        rec.setStoredName(stored);
        rec.setSize(file.getSize());
        rec.setCreatedAt(LocalDateTime.now());
        fileMapper.insert(rec);
        // 下载端点按数字主键 /api/v1/files/{id} 路由，url 必须在拿到 id 后回填
        rec.setUrl("/api/v1/files/" + rec.getId());
        fileMapper.updateById(rec);
        return ApiResponse.ok(Map.of(
                "id", rec.getId(),
                "name", original,
                "url", rec.getUrl(),
                "size", file.getSize()));
    }

    /**
     * 网盘文件列表（管理端首页「网盘」分区）。
     *
     * <p>按当前登录用户过滤（{@code user_id = 我}），仅取活行（{@code @TableLogic} 软删自动排除）；
     * 支持分页（{@code page}/{@code size}）与按文件名模糊（{@code keyword}）。</p>
     *
     * <p>返回 {@code {list,total,page,size}}；{@code list} 每行含
     * {@code id,name,sizeBytes,contentType,createdAt}。注：{@code sys_file} 表无独立
     * content_type 列，{@code contentType} 由文件名后缀推导（best-effort）。</p>
     */
    @GetMapping
    public ApiResponse<Map<String, Object>> list(
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "20") int size,
            @RequestParam(name = "keyword", required = false) String keyword) {
        AuthUser user = AuthUserContext.require();
        LambdaQueryWrapper<SysFile> w = new LambdaQueryWrapper<SysFile>()
                .eq(SysFile::getUserId, user.getUserId())
                .orderByDesc(SysFile::getCreatedAt);
        if (keyword != null && !keyword.isBlank()) {
            w.like(SysFile::getOriginalName, keyword);
        }
        Page<SysFile> p = fileMapper.selectPage(
                new Page<>(Math.max(page, 1), Math.max(size, 1)), w);
        List<Map<String, Object>> list = new ArrayList<>(p.getRecords().size());
        for (SysFile f : p.getRecords()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", f.getId());
            m.put("name", f.getOriginalName());
            m.put("sizeBytes", f.getSize());
            m.put("contentType", deriveContentType(f.getOriginalName()));
            m.put("createdAt", f.getCreatedAt() == null ? null : f.getCreatedAt().toString());
            list.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("list", list);
        out.put("total", p.getTotal());
        out.put("page", p.getCurrent());
        out.put("size", p.getSize());
        return ApiResponse.ok(out);
    }

    /** 由文件名后缀推导 MIME（sys_file 未存 content_type，前端列表展示用 best-effort 值）。 */
    private static String deriveContentType(String originalName) {
        if (originalName == null) {
            return "application/octet-stream";
        }
        String n = originalName.toLowerCase();
        if (n.endsWith(".pdf")) return "application/pdf";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "image/jpeg";
        if (n.endsWith(".gif")) return "image/gif";
        if (n.endsWith(".webp")) return "image/webp";
        if (n.endsWith(".bmp")) return "image/bmp";
        if (n.endsWith(".doc")) return "application/msword";
        if (n.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        if (n.endsWith(".xls")) return "application/vnd.ms-excel";
        if (n.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        if (n.endsWith(".ppt")) return "application/vnd.ms-powerpoint";
        if (n.endsWith(".pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        if (n.endsWith(".txt")) return "text/plain";
        if (n.endsWith(".csv")) return "text/csv";
        if (n.endsWith(".html") || n.endsWith(".htm")) return "text/html";
        if (n.endsWith(".json")) return "application/json";
        if (n.endsWith(".xml")) return "application/xml";
        if (n.endsWith(".zip")) return "application/zip";
        if (n.endsWith(".rar")) return "application/x-rar-compressed";
        if (n.endsWith(".7z")) return "application/x-7z-compressed";
        if (n.endsWith(".mp3")) return "audio/mpeg";
        if (n.endsWith(".wav")) return "audio/wav";
        if (n.endsWith(".mp4")) return "video/mp4";
        if (n.endsWith(".mov")) return "video/quicktime";
        if (n.endsWith(".webm")) return "video/webm";
        return "application/octet-stream";
    }

    @GetMapping("/{id}")
    public ResponseEntity<Resource> download(@PathVariable Long id) {
        SysFile rec = fileMapper.selectById(id);
        if (rec == null || rec.getStoredName() == null) {
            throw BizException.notFound("文件不存在：" + id);
        }
        Path target = root.resolve(rec.getStoredName());
        if (!Files.exists(target) || !Files.isRegularFile(target)) {
            throw BizException.notFound("文件已不存在：" + id);
        }
        Resource resource = new FileSystemResource(target);
        String disposition = "inline; filename*=UTF-8''"
                + URLEncoder.encode(rec.getOriginalName() == null ? "file" : rec.getOriginalName(), StandardCharsets.UTF_8);
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .header(HttpHeaders.CONTENT_DISPOSITION, disposition)
                .body(resource);
    }
}
