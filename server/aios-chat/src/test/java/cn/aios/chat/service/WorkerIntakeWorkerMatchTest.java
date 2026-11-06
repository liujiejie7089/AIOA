package cn.aios.chat.service;

import cn.aios.resource.entity.AgentWorker;
import cn.aios.resource.mapper.AgentWorkerMapper;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「意图 → 在册数字员工候选」的定点验收（2026-11-06）。
 *
 * <p><b>为什么必须有这条</b>：H5「新工作任务」输完一句话就要跳到对应数字人，判据是
 * {@code POST /v1/workers/intent} 返回的 {@code workers} 候选。而意图分类器只吐 4 个
 * {@code WorkerRole} 角色码，OA 模块是 43 个 {@code OA_*} 模块码 —— 两套编码不互译，
 * 候选一旦算不出来，界面就退化成「未能识别类型，请手动选择」（用户报的原始现象）。
 * 这条用例把候选算法钉住：类型直译、名称关键词、同分时平台模块优先、以及**不许瞎猜**。</p>
 *
 * <p>不启 Spring：{@code AgentWorkerMapper} 用 Mockito 替身返回一份「迷你租户清单」，
 * 其余协作者传 null（{@code matchWorkers} 只用到 mapper 与 user，是纯读路径）。</p>
 */
class WorkerIntakeWorkerMatchTest {

    /** 在册清单：两个 OA 模块 + 一个自建 GENERAL（本环境真有一台叫「每日考勤」的）。 */
    private static List<AgentWorker> roster() {
        return List.of(
                worker(1L, "公文助手数字人", "OA_DOC"),
                worker(2L, "考勤管理数字人", "OA_ATTENDANCE"),
                worker(3L, "工作周报数字人", "OA_WEEKLY"),
                worker(4L, "请假助手数字人", "OA_LEAVE"),
                worker(5L, "每日考勤", "GENERAL"));
    }

    private static AgentWorker worker(Long id, String name, String type) {
        AgentWorker w = new AgentWorker();
        w.setId(id);
        w.setName(name);
        w.setWorkerType(type);
        w.setEnabled(1);
        w.setIsTemplate(0);
        w.setTenantId(7L);
        return w;
    }

    private static WorkerIntakeService serviceWith(List<AgentWorker> rows) {
        AgentWorkerMapper mapper = Mockito.mock(AgentWorkerMapper.class);
        Mockito.when(mapper.selectList(Mockito.<Wrapper<AgentWorker>>any())).thenReturn(rows);
        return new WorkerIntakeService(new ObjectMapper(), null, null, null, null, null, null,
                null, null, null, mapper, null, null);
    }

    private static AuthUser user() {
        // AuthUser 带 @Builder（只生成全参构造），故走静态工厂，不 new 空对象
        return AuthUser.of(1L, 7L, "test", "测试账号", java.util.List.of());
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> match(WorkerIntakeService svc, String text, String role) {
        try {
            java.lang.reflect.Method m = WorkerIntakeService.class
                    .getDeclaredMethod("matchWorkers", AuthUser.class, String.class, String.class);
            m.setAccessible(true);
            return (List<Map<String, Object>>) m.invoke(svc, user(), text, role);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }

    @Test
    @DisplayName("角色码直译：LEAVE_APPROVER → OA_LEAVE（两套编码靠这一条打通）")
    void roleCodeMapsToModuleCode() {
        List<Map<String, Object>> got = match(serviceWith(roster()), "我要请假三天", "LEAVE_APPROVER");
        assertFalse(got.isEmpty(), "请假意图必须给出候选，否则 H5 只能弹「请手动选择」");
        assertEquals("请假助手数字人", got.get(0).get("name"));
        assertEquals("OA_LEAVE", got.get(0).get("workerType"));
    }

    @Test
    @DisplayName("名称关键词：意图分类器给不出专用类型时，靠名字把「考勤」认出来")
    void nameKeywordFindsModule() {
        List<Map<String, Object>> got = match(serviceWith(roster()), "考勤异常怎么申诉", "GENERAL");
        assertFalse(got.isEmpty());
        assertEquals("考勤管理数字人", got.get(0).get("name"));
    }

    @Test
    @DisplayName("同分时平台 OA 模块优先于自建 GENERAL 员工（「每日考勤」不该抢）")
    void oaModuleWinsTie() {
        List<Map<String, Object>> got = match(serviceWith(roster()), "考勤异常怎么申诉", "GENERAL");
        assertTrue(got.size() >= 2, "两台都命中时都要进候选，交给上层判唯一最高分");
        assertEquals("考勤管理数字人", got.get(0).get("name"), "同分第一必须是 OA 模块");
        assertEquals("每日考勤", got.get(1).get("name"));
        int top = (int) got.get(0).get("score");
        int second = (int) got.get(1).get("score");
        assertTrue(top > second, "OA 模块应严格高于同分的 GENERAL 员工，否则前端无法判定唯一");
    }

    @Test
    @DisplayName("词尾 2 字也能命中：周报 → 工作周报数字人")
    void tailKeywordHits() {
        List<Map<String, Object>> got = match(serviceWith(roster()), "帮我起草一份周报", "GENERAL");
        assertFalse(got.isEmpty());
        assertEquals("工作周报数字人", got.get(0).get("name"));
    }

    @Test
    @DisplayName("无信息问句不许瞎猜：候选为空，由用户自己选")
    void noMatchStaysEmpty() {
        assertTrue(match(serviceWith(roster()), "今天天气怎么样", "GENERAL").isEmpty());
    }

    @Test
    @DisplayName("GENERAL 缺省码不当类型码用（worker_type=GENERAL 的自建员工不会被无脑选中）")
    void generalIsNotATypeCode() {
        List<AgentWorker> onlyGeneral = List.of(worker(9L, "每日考勤", "GENERAL"));
        assertTrue(match(serviceWith(onlyGeneral), "随便问点什么", "GENERAL").isEmpty(),
                "缺省角色码 + 无关键词命中 ⇒ 不得把任何员工当默认落点");
    }

    @Test
    @DisplayName("user / text 为空或 mapper 缺失时不抛（意图接口不能因为候选而整体失败）")
    void degradesQuietly() {
        WorkerIntakeService svc = new WorkerIntakeService(new ObjectMapper(), null, null, null, null,
                null, null, null, null, null, null, null, null);
        assertTrue(match(svc, "我要请假", "LEAVE_APPROVER").isEmpty());
        assertTrue(match(serviceWith(roster()), "", "LEAVE_APPROVER").isEmpty());
    }
}
