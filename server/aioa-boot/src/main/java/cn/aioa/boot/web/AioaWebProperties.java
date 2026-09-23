package cn.aioa.boot.web;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 单端口入口配置（aioa.web.*）。
 *
 * <p>默认值对齐 compose 里的容器内挂载点：H5 单文件挂到 {@code /app/h5}、
 * 管理端静态产物挂到 {@code /app/web}。本地联调时用命令行 / 环境变量覆盖，例如
 * <pre>
 * --aioa.web.h5-dir=D:/repo/user-client --aioa.web.web-dir=D:/repo/web/apps/shell/dist
 * </pre>
 * 详见 {@code docs/33-单端口部署改造实施计划.md}。
 */
@Data
@ConfigurationProperties(prefix = "aioa.web")
public class AioaWebProperties {

    /** 是否启用单端口前缀（关掉后 /aioa/** 全部 404，既有 /api/** 不受影响）。 */
    private boolean enabled = true;

    /** 对外入口前缀，接口挂在 {@code <prefix>/api}。留空则不做剥离。 */
    private String prefix = "/aioa";

    /** 用户端 H5 静态目录（内含 index.html）。 */
    private String h5Dir = "/app/h5";

    /** 管理端静态目录（dist 产物；其下可有 subapps/<name>/）。 */
    private String webDir = "/app/web";

    /** H5 的首页文件名（同时作为 SPA 回退目标）。 */
    private String h5Index = "index.html";

    /** 管理端的首页文件名（同时作为 SPA 回退目标）。 */
    private String webIndex = "index.html";
}
