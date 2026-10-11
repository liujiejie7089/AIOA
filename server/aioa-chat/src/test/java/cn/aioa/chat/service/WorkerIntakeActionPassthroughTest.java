package cn.aioa.chat.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.lang.reflect.Field;
import java.net.HttpURLConnection;
import java.net.URI;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「动作意图」跨层透传的定点验收（2026-10 需求：上传文件 / 上报花费改由对话意图驱动）。
 *
 * <p><b>为什么单独写这一条</b>：H5 端的「自动弹窗」只认 {@code POST /api/v1/workers/intent}
 * 返回体里的 {@code action} 键。这一维度由 Python 侧 {@code worker_intake.classify()} 一处判定，
 * Java 侧只做透传 —— 而透传恰恰是最容易「静默丢掉」的一层：少一行 {@code out.put("action", ...)}，
 * Python 的单测全绿、Java 编译也照过，只有端到端才会暴露。故这里把这一层单独钉住。</p>
 *
 * <p><b>为什么打真实 agent 而不是 stub</b>：本用例要证的正是「Java 与 Python 之间的契约」，
 * stub 掉 HTTP 就变成了在测自己写的假数据。前置 {@code agent :8000} 不可达时 <b>整类 SKIP</b>
 * （{@link Assumptions}），而不是伪装 PASS —— 与项目「前置不满足就记 SKIP 并非 0」的口径一致。</p>
 *
 * <p>本类不启动 Spring 上下文：{@link WorkerIntakeService#intent(String)} 只用到
 * {@code objectMapper} 与 {@code agentBaseUrl}，其余协作者在本用例中传 null（方法体不触达）。</p>
 */
class WorkerIntakeActionPassthroughTest {

    private static final String AGENT = "http://127.0.0.1:8000";

    private static WorkerIntakeService service;

    @BeforeAll
    static void setUp() throws Exception {
        Assumptions.assumeTrue(agentUp(),
                "agent " + AGENT + " 不可达 ⇒ SKIP（本用例刻意打真实分类链路，不 stub HTTP）");
        // 协作者全部传 null：intent() 只读 objectMapper / agentBaseUrl / http。
        service = new WorkerIntakeService(new ObjectMapper(), null, null, null, null, null, null, null);
        Field baseUrl = WorkerIntakeService.class.getDeclaredField("agentBaseUrl");
        baseUrl.setAccessible(true);
        baseUrl.set(service, AGENT);
    }

    private static boolean agentUp() {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) URI.create(AGENT + "/docs").toURL().openConnection();
            conn.setConnectTimeout(2000);
            conn.setReadTimeout(2000);
            conn.setRequestMethod("GET");
            conn.getResponseCode();          // 任何 HTTP 状态码都算「活着」
            return true;
        } catch (IOException e) {
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    // ------------------------------------------------------------ 正例：动作必须被透传

    @Test
    @DisplayName("★说「帮我上传一下这个文件」→ Java 透传出 action=UPLOAD_FILE")
    void uploadIntentPassesThrough() {
        Map<String, Object> out = service.intent("帮我上传一下这个文件");
        assertTrue(out.containsKey("action"),
                "响应缺少 action 键 —— Java 层没有把 Python 的动作维度透出（H5 会因此永不弹窗）：" + out);
        assertEquals("UPLOAD_FILE", out.get("action"), String.valueOf(out));
        assertEquals("上传文件", out.get("actionName"), String.valueOf(out));
    }

    @Test
    @DisplayName("★宾语在前的语序「把项目合同传上去」→ action=UPLOAD_FILE")
    void objectFirstUploadIntentPassesThrough() {
        Map<String, Object> out = service.intent("把项目合同传上去");
        assertEquals("UPLOAD_FILE", out.get("action"), String.valueOf(out));
    }

    @Test
    @DisplayName("★说「我要上报一笔差旅花费」→ action=REPORT_EXPENSE")
    void reportExpenseIntentPassesThrough() {
        Map<String, Object> out = service.intent("我要上报一笔差旅花费");
        assertEquals("REPORT_EXPENSE", out.get("action"), String.valueOf(out));
        assertEquals("上报花费", out.get("actionName"), String.valueOf(out));
    }

    // ------------------------------------------------------------ 负例：疑问句不得被判成「要开窗口」

    @Test
    @DisplayName("★「公司费用报销制度是怎么规定的」→ action 必须是 null，且角色不回归（KB_ASSISTANT）")
    void questionAboutExpenseIsNotAnAction() {
        Map<String, Object> out = service.intent("公司费用报销制度是怎么规定的");
        assertTrue(out.containsKey("action"), "action 键必须恒定存在（值为 null 也要有）：" + out);
        assertNull(out.get("action"), "制度类提问被误判成「要上报花费」：" + out);
        assertEquals("KB_ASSISTANT", out.get("role"), "角色判定被动作维度带偏了：" + out);
    }

    @Test
    @DisplayName("负例：「帮我起草一份通知」→ action=null，角色仍是 DOC_DRAFTER")
    void docDraftHasNoAction() {
        Map<String, Object> out = service.intent("帮我起草一份通知");
        assertNull(out.get("action"), String.valueOf(out));
        assertEquals("DOC_DRAFTER", out.get("role"), String.valueOf(out));
    }

    @Test
    @DisplayName("负例/边界：空文本 → action 键在、值为 null（schema 恒定，H5 靠「键在值 null」区分正常对话）")
    void actionKeyPresentOnEmptyText() {
        Map<String, Object> out = service.intent("");
        assertTrue(out.containsKey("action"), "空文本路径漏补 action 键：" + out);
        assertNull(out.get("action"), String.valueOf(out));
    }
}
