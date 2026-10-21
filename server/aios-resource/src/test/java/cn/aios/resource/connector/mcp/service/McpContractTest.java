package cn.aios.resource.connector.mcp.service;

import cn.aios.resource.connector.mcp.controller.McpServerController;
import cn.aios.resource.connector.mcp.service.McpRegistryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * MCP 两处「跨语言/字符串」接缝的回归哨兵（都不需要起服务）。
 *
 * <p>1) hub 基址去尾斜杠：原始写法 {@code replaceAll("/+$/", "")} 的正则多了一个结尾斜杠，
 * 永不匹配也不报错 ⇒ {@code …:8099/} 会拼成 {@code …:8099//mcp/qq_mail}，hub 404，
 * agent 静默发现不到内置工具。判据必须是「带尾斜杠时真的被削掉」。</p>
 *
 * <p>2) hub 发的是 {@code arguments}，Java {@code CallBody} 的字段叫 {@code args}，
 * 靠 record component 上的 {@code @JsonAlias} 兼容。这条链路（内置工具）在端到端哨兵里
 * 走不到（要真实邮箱/企微凭据），所以在这里用真实类 + 真实 Jackson 钉住两种键名。</p>
 */
class McpContractTest {

    @Test
    void trimHubBase_应削掉任意数量的尾斜杠() {
        assertEquals("http://mcp-hub:8099", McpRegistryService.trimHubBase("http://mcp-hub:8099"));
        assertEquals("http://mcp-hub:8099", McpRegistryService.trimHubBase("http://mcp-hub:8099/"));
        assertEquals("http://mcp-hub:8099", McpRegistryService.trimHubBase("http://mcp-hub:8099///"));
        assertEquals("", McpRegistryService.trimHubBase(null));
    }

    @Test
    void callBody_两种键名都要解析进args() throws Exception {
        ObjectMapper m = new ObjectMapper();
        McpServerController.CallBody hub = m.readValue(
                "{\"tool\":\"read_message\",\"arguments\":{\"uid\":42}}", McpServerController.CallBody.class);
        McpServerController.CallBody nativeArgs = m.readValue(
                "{\"tool\":\"read_message\",\"args\":{\"uid\":42}}", McpServerController.CallBody.class);
        McpServerController.CallBody none = m.readValue(
                "{\"tool\":\"list_folders\"}", McpServerController.CallBody.class);

        assertEquals(Map.of("uid", 42), hub.args(), "hub 的 arguments 键必须能解析");
        assertEquals(Map.of("uid", 42), nativeArgs.args());
        assertTrue(none.args() == null, "无参工具不应构造空 map");
    }
}
