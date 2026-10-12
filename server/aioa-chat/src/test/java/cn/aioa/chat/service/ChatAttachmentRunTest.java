package cn.aioa.chat.service;

import cn.aioa.chat.dto.AgentRunRequest;
import cn.aioa.chat.entity.ChatMessage;
import cn.aioa.common.mybatis.JsonListTypeHandler;
import cn.aioa.resource.entity.SysFile;
import com.baomidou.mybatisplus.annotation.TableField;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 对话内文档上传（不进知识库）链路定点验收。
 *
 * <p><b>为什么单独写这一条</b>：本轮改动最容易被「静默丢掉」的一层是三端契约 ——
 * ChatMessage.attachments 是否被 MyBatis 持久化到新列、AgentRunRequest.attachment_docs 的
 * JSON 键名是否与 agent 侧 {@code RunRequest.attachment_docs} 完全一致、以及 resolveAttachments
 * 的解析 / 截断 / 失败处理是否正确。这些漏掉任一，编译照过，只有端到端才暴露。故把它们钉死。</p>
 *
 * <p><b>不启动 Spring</b>：RunService 用全 mock 协作者构造（15 个 final 构造参数），
 * uploadDir 与私有方法经反射注入 / 调用。这与本模块既有 OrgConfigScopeTest /
 * WorkerIntakeActionPassthroughTest 的「纯单测、不抬 Spring」口径一致。</p>
 */
class ChatAttachmentRunTest {

    private static final int VIEW_MAX = 20000; // 仅断言用；实现必须引用 KbController.VIEW_MAX_CHARS（同源）

    /** 按 RequiredArgsConstructor 的字段声明顺序构造 RunService（末尾两个 field 为本轮新增）。 */
    private static RunService buildService() {
        return new RunService(
                mock(cn.aioa.chat.mapper.ChatConversationMapper.class),
                mock(cn.aioa.chat.mapper.ChatMessageMapper.class),
                mock(cn.aioa.chat.mapper.AgentRunMapper.class),
                mock(org.springframework.web.reactive.function.client.WebClient.class),
                mock(cn.aioa.security.ServiceTokenProvider.class),
                new ObjectMapper(),
                mock(java.util.concurrent.ScheduledExecutorService.class),
                mock(cn.aioa.chat.config.AgentProperties.class),
                mock(cn.aioa.resource.service.BillingService.class),
                mock(cn.aioa.resource.service.ActivityLogService.class),
                mock(cn.aioa.chat.service.ContentGuardService.class),
                mock(cn.aioa.resource.mapper.AgentWorkerMapper.class),
                mock(cn.aioa.project.port.PmAiScopePort.class),
                mock(cn.aioa.resource.mapper.SysFileMapper.class),
                mock(cn.aioa.resource.service.KbFileParser.class));
    }

    private static RunService buildResolvingService(Path uploadDir,
                                                   cn.aioa.resource.mapper.SysFileMapper fileMapper,
                                                   cn.aioa.resource.service.KbFileParser parser) throws Exception {
        RunService svc = new RunService(
                mock(cn.aioa.chat.mapper.ChatConversationMapper.class),
                mock(cn.aioa.chat.mapper.ChatMessageMapper.class),
                mock(cn.aioa.chat.mapper.AgentRunMapper.class),
                mock(org.springframework.web.reactive.function.client.WebClient.class),
                mock(cn.aioa.security.ServiceTokenProvider.class),
                new ObjectMapper(),
                mock(java.util.concurrent.ScheduledExecutorService.class),
                mock(cn.aioa.chat.config.AgentProperties.class),
                mock(cn.aioa.resource.service.BillingService.class),
                mock(cn.aioa.resource.service.ActivityLogService.class),
                mock(cn.aioa.chat.service.ContentGuardService.class),
                mock(cn.aioa.resource.mapper.AgentWorkerMapper.class),
                mock(cn.aioa.project.port.PmAiScopePort.class),
                fileMapper,
                parser);
        Field f = RunService.class.getDeclaredField("uploadDir");
        f.setAccessible(true);
        f.set(svc, uploadDir.toString());
        return svc;
    }

    // ------------------------------------------------------------ 契约1：AgentRunRequest 键名

    @Test
    @DisplayName("★AgentRunRequest.attachmentDocs 序列化键名必须是 attachment_docs（与 agent 侧契约一致）")
    void attachmentDocsJsonKey() throws Exception {
        AgentRunRequest req = new AgentRunRequest();
        req.setAttachmentDocs(List.of(Map.of(
                "file_id", 123, "name", "报告.pdf", "text", "正文…", "truncated", false)));
        String json = new ObjectMapper().writeValueAsString(req);
        assertTrue(json.contains("\"attachment_docs\""),
                "缺少 attachment_docs 键，agent 侧 RunRequest.attachment_docs 收不到：" + json);
    }

    // ------------------------------------------------------------ 契约2：ChatMessage 持久化映射

    @Test
    @DisplayName("★ChatMessage.attachments 经 JsonListTypeHandler 落 JSON（新列确实被持久化，而非被 MyBatis 忽略）")
    void chatMessageAttachmentsMapping() throws Exception {
        Field att = ChatMessage.class.getDeclaredField("attachments");
        TableField tf = att.getAnnotation(TableField.class);
        assertNotNull(tf, "attachments 缺少 @TableField");
        assertEquals(JsonListTypeHandler.class, tf.typeHandler(),
                "attachments 未用 JsonListTypeHandler，不会被持久化为 JSON");
        // 字段可写可读：setter/getter 由 @Data 生成，证明 start() 能落库、subscribe() 能回读
        ChatMessage m = new ChatMessage();
        m.setAttachments(List.of(Map.of("file_id", 1, "name", "a", "text", "t", "truncated", false)));
        assertNotNull(m.getAttachments());
        assertEquals(1, ((Map<?, ?>) m.getAttachments().get(0)).get("file_id"));
    }

    // ------------------------------------------------------------ 契约3：resolveAttachments 解析/截断/失败

    @Test
    @DisplayName("★resolveAttachments：正常文件解析出 {file_id,name,text,truncated}，超长截断到 20000")
    void resolveAttachmentsParsesAndTruncates() throws Exception {
        Path dir = Files.createTempDirectory("att-test");
        Path file = dir.resolve("report.pdf");
        Files.write(file, "raw-bytes-do-not-matter".getBytes(StandardCharsets.UTF_8));

        SysFile rec = new SysFile();
        rec.setOriginalName("report.pdf");
        rec.setStoredName(file.getFileName().toString());
        cn.aioa.resource.mapper.SysFileMapper fileMapper = mock(cn.aioa.resource.mapper.SysFileMapper.class);
        when(fileMapper.selectById(1L)).thenReturn(rec);

        // 模拟解析出 25000 字符（超过 VIEW_MAX=20000），验证截断
        String longText = "x".repeat(VIEW_MAX + 5000);
        cn.aioa.resource.service.KbFileParser parser = mock(cn.aioa.resource.service.KbFileParser.class);
        when(parser.parse(anyString(), any(byte[].class))).thenReturn(longText);

        RunService svc = buildResolvingService(dir, fileMapper, parser);
        Method m = RunService.class.getDeclaredMethod("resolveAttachments", List.class);
        m.setAccessible(true);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> result = (List<Map<String, Object>>) m.invoke(svc, List.of(1L));

        assertEquals(1, result.size());
        Map<String, Object> entry = result.get(0);
        assertEquals(1L, entry.get("file_id"));
        assertEquals("report.pdf", entry.get("name"));
        assertEquals(false, entry.containsKey("error"), "正常解析不应有 error：" + entry);
        String text = (String) entry.get("text");
        assertEquals(VIEW_MAX, text.length(), "超长正文应被截断到 VIEW_MAX");
        assertEquals(true, entry.get("truncated"));
    }

    @Test
    @DisplayName("★resolveAttachments：文件不存在 / 缺失不 500，产出 error 项且 text 为空")
    void resolveAttachmentsMissingFileNoThrow() throws Exception {
        Path dir = Files.createTempDirectory("att-test-2");
        cn.aioa.resource.mapper.SysFileMapper fileMapper = mock(cn.aioa.resource.mapper.SysFileMapper.class);
        when(fileMapper.selectById(2L)).thenReturn(null); // 元数据不存在
        when(fileMapper.selectById(3L)).thenReturn(new SysFile() {{
            setOriginalName("gone.pdf");
            setStoredName("gone.pdf"); // 磁盘无此文件
        }});
        cn.aioa.resource.service.KbFileParser parser = mock(cn.aioa.resource.service.KbFileParser.class);

        RunService svc = buildResolvingService(dir, fileMapper, parser);
        Method m = RunService.class.getDeclaredMethod("resolveAttachments", List.class);
        m.setAccessible(true);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> result = (List<Map<String, Object>>) m.invoke(svc, List.of(2L, 3L));

        assertEquals(2, result.size());
        assertEquals("文件不存在", result.get(0).get("error"));
        assertEquals("", result.get(0).get("text"));
        assertEquals("文件已不存在", result.get(1).get("error"));
        assertEquals("", result.get(1).get("text"));
    }

    @Test
    @DisplayName("★resolveAttachments：解析抛错（不支持格式）不 500，产出 error 项")
    void resolveAttachmentsParseErrorNoThrow() throws Exception {
        Path dir = Files.createTempDirectory("att-test-3");
        Path file = dir.resolve("bad.xyz");
        Files.write(file, "x".getBytes(StandardCharsets.UTF_8));
        SysFile rec = new SysFile();
        rec.setOriginalName("bad.xyz");
        rec.setStoredName(file.getFileName().toString());
        cn.aioa.resource.mapper.SysFileMapper fileMapper = mock(cn.aioa.resource.mapper.SysFileMapper.class);
        when(fileMapper.selectById(5L)).thenReturn(rec);
        // KbFileParser.parse 对不支持格式抛 BizException（RuntimeException）
        cn.aioa.resource.service.KbFileParser parser = mock(cn.aioa.resource.service.KbFileParser.class);
        when(parser.parse(anyString(), any(byte[].class)))
                .thenThrow(new cn.aioa.common.exception.BizException("暂不支持的文件格式"));

        RunService svc = buildResolvingService(dir, fileMapper, parser);
        Method m = RunService.class.getDeclaredMethod("resolveAttachments", List.class);
        m.setAccessible(true);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> result = (List<Map<String, Object>>) m.invoke(svc, List.of(5L));

        assertEquals(1, result.size());
        assertEquals("暂不支持的文件格式", result.get(0).get("error"));
        assertEquals("", result.get(0).get("text"));
        assertFalse(result.get(0).containsKey("truncated") && (Boolean) result.get(0).get("truncated"));
    }

    @Test
    @DisplayName("★resolveAttachments：空入参返回 null（无附件时新列存 NULL，不落空数组）")
    void resolveAttachmentsEmptyReturnsNull() throws Exception {
        RunService svc = buildResolvingService(Files.createTempDirectory("att-test-4"),
                mock(cn.aioa.resource.mapper.SysFileMapper.class),
                mock(cn.aioa.resource.service.KbFileParser.class));
        Method m = RunService.class.getDeclaredMethod("resolveAttachments", List.class);
        m.setAccessible(true);
        assertNull(m.invoke(svc, new Object[]{null}));
        assertNull(m.invoke(svc, List.of()));
    }

    // ------------------------------------------------------------ 契约4：历史回填前缀格式化

    @Test
    @DisplayName("★formatAttachmentDocs：把附件正文拼成【参考文档】前缀（历史轮次回填用）")
    void formatAttachmentDocsPrefix() throws Exception {
        List<Object> atts = List.of(
                Map.of("file_id", 1, "name", "报告.pdf", "text", "这是正文", "truncated", false),
                Map.of("file_id", 2, "name", "缺.pdf", "text", "", "error", "文件不存在"));
        Method m = RunService.class.getDeclaredMethod("formatAttachmentDocs", List.class);
        m.setAccessible(true);
        String prefix = (String) m.invoke(null, atts);

        assertTrue(prefix.contains("【参考文档】《报告.pdf》"), prefix);
        assertTrue(prefix.contains("这是正文"), prefix);
        assertTrue(prefix.contains("【以上为参考文档】"), prefix);
        // 失败项也回显原因，不静默
        assertTrue(prefix.contains("（解析失败：文件不存在）"), prefix);
    }
}
