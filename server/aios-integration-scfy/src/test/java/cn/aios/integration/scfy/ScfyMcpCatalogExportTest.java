package cn.aios.integration.scfy;

import cn.aios.integration.scfy.contract.ScfyCatalog;
import cn.aios.integration.scfy.contract.ScfyEndpoint;
import cn.aios.integration.scfy.contract.ScfyParam;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 把 {@link ScfyCatalog} 的全部可用接口导出为 MCP hub 可直接读取的 catalog.json。
 *
 * <p><b>为什么用导出而不是在 Python 侧手抄</b>：接口清单（参数名、必填性、枚举、实测校正）
 * 的唯一事实源是 ScfyCatalog。手抄会立刻变成第二份真相并漂移 —— 而 scfy 对错误参数
 * 是「静默返回空集」，漂移会伪装成「没有数据」。这里让 Python 侧只读导出物，
 * 新增接口时重跑本测试即可（{@code -Dscfy.mcp.catalog=<绝对路径>}）。
 * 导出范围是 {@link ScfyCatalog#mcpAvailable()}：包含 Java 已绑定的接口与
 * {@code MCP_ONLY} 接口 —— 后者不要求 Java @AiosTool，也不进 agent 匹配/矩阵。</p>
 *
 * <p>默认不会覆盖文件：必须显式 {@code -Dscfy.mcp.export=true}。</p>
 */
class ScfyMcpCatalogExportTest {

    @Test
    void exportCatalogForMcpHub() throws Exception {
        if (!Boolean.getBoolean("scfy.mcp.export")) {
            return;
        }
        String explicit = System.getProperty("scfy.mcp.catalog");
        Path out = explicit != null ? Path.of(explicit) : defaultHubCatalog();
        if (out == null) {
            throw new IllegalStateException("找不到 mcp-hub 目录：请用 -Dscfy.mcp.catalog=<绝对路径> 指定产物位置");
        }

        List<Map<String, Object>> tools = new ArrayList<>();
        for (ScfyEndpoint ep : ScfyCatalog.mcpAvailable()) {
            Map<String, Object> tool = new LinkedHashMap<>();
            tool.put("id", ep.id());
            tool.put("group", ep.group());
            tool.put("path", ep.fullPath());
            tool.put("summary", ep.summary());
            if (ep.note() != null && !ep.note().isBlank()) {
                tool.put("note", ep.note());
            }
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            Map<String, Object> props = new LinkedHashMap<>();
            List<String> required = new ArrayList<>();
            for (ScfyParam p : ep.params()) {
                Map<String, Object> prop = new LinkedHashMap<>();
                // areaCode 形态校验在 Python 侧按 12 位数字处理，schema 统一暴露为 string
                prop.put("type", "string".equals(p.type()) || "areaCode".equals(p.type()) ? "string" : p.type());
                String desc = p.description();
                if (p.example() != null && !p.example().isBlank()) {
                    desc = desc + "（示例：" + p.example() + "）";
                }
                if (p.docNote() != null && !p.docNote().isBlank()) {
                    desc = desc + "。注意：" + p.docNote();
                }
                if ("areaCode".equals(p.type())) {
                    desc = desc + "。必须是 12 位数字行政区划编码";
                }
                prop.put("description", desc);
                if (p.hasEnums()) {
                    prop.put("enum", p.enums());
                }
                props.put(p.name(), prop);
                if (p.required()) {
                    required.add(p.name());
                }
            }
            schema.put("properties", props);
            schema.put("required", required);
            tool.put("inputSchema", schema);
            tools.add(tool);
        }

        Map<String, Object> root = new LinkedHashMap<>();
        root.put("source", "ScfyCatalog (server/aios-integration-scfy)");
        root.put("generatedBy", "ScfyMcpCatalogExportTest -Dscfy.mcp.export=true");
        root.put("count", tools.size());
        root.put("tools", tools);

        Files.createDirectories(out.getParent());
        Files.writeString(out, new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT)
                .writeValueAsString(root), StandardCharsets.UTF_8);
        System.out.println("[scfy-mcp-export] " + tools.size() + " tools -> " + out.toAbsolutePath());
    }

    private static Path defaultHubCatalog() {
        for (Path p : List.of(
                Path.of(".").resolve("mcp-hub/mcp_hub/scfy/catalog.json").toAbsolutePath().normalize(),
                Path.of("..").resolve("mcp-hub/mcp_hub/scfy/catalog.json").toAbsolutePath().normalize())) {
            if (Files.isDirectory(p.getParent().getParent())) {
                return p;
            }
        }
        return null;
    }
}
