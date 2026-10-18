package cn.aios.resource.controller;

import cn.aios.common.exception.BizException;
import cn.aios.common.resp.ApiResponse;
import cn.aios.resource.entity.SysFile;
import cn.aios.resource.mapper.SysFileMapper;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
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
