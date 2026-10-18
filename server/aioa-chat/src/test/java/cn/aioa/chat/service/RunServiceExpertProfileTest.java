package cn.aioa.chat.service;

import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.model.ExpertSettings;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link RunService#expertProfileMap(AiExpert, ExpertSettings)} 纯函数单测（不需要 Spring）。
 *
 * <p>覆盖：有 prompt 时 system_prompt 存在；空 prompt / 空 intro 时该键不出现（而非空串）；
 * tags / recs 原样带出；key / name 必带。</p>
 */
class RunServiceExpertProfileTest {

    private static AiExpert expert(String key, String name, String summary, String intro,
                                  List<Object> tags, List<Object> recs) {
        AiExpert e = new AiExpert();
        e.setExpertKey(key);
        e.setName(name);
        e.setSummary(summary);
        e.setIntro(intro);
        e.setTags(tags);
        e.setRecs(recs);
        return e;
    }

    private static ExpertSettings settings(String systemPrompt, String knowledgeScope) {
        ExpertSettings s = new ExpertSettings();
        s.setSystemPrompt(systemPrompt);
        s.setKnowledgeScope(knowledgeScope);
        return s;
    }

    @Test
    @DisplayName("有 prompt 时 system_prompt 存在且为原值")
    void promptPresentWhenSet() {
        AiExpert e = expert("policy", "政策专家", "简介", "详情", null, null);
        ExpertSettings s = settings("你是政策领域专家，依据现行法规作答。", "政策/法规");
        Map<String, Object> m = RunService.expertProfileMap(e, s);
        assertNotNull(m.get("system_prompt"), "system_prompt 应存在");
        assertEquals("你是政策领域专家，依据现行法规作答。", m.get("system_prompt"));
        assertEquals("policy", m.get("key"));
        assertEquals("政策专家", m.get("name"));
        assertEquals("简介", m.get("summary"));
    }

    @Test
    @DisplayName("空 prompt 时 system_prompt 键不出现（而非空串）")
    void emptyPromptKeyAbsent() {
        AiExpert e = expert("legal", "法务专家", null, null, null, null);
        ExpertSettings s = settings("", "  "); // 空串 + 空白
        Map<String, Object> m = RunService.expertProfileMap(e, s);
        assertFalse(m.containsKey("system_prompt"), "空 prompt 时不应出现 system_prompt 键");
        assertFalse(m.containsKey("summary"), "null summary 不应出现键");
        assertFalse(m.containsKey("intro"), "null intro 不应出现键");
        assertFalse(m.containsKey("knowledge_scope"), "空 knowledge_scope 不应出现键");
        // key / name 仍必带
        assertEquals("legal", m.get("key"));
        assertEquals("法务专家", m.get("name"));
    }

    @Test
    @DisplayName("null ExpertSettings 时仅专家基础键，无 system_prompt / knowledge_scope")
    void nullSettingsNoPrompt() {
        AiExpert e = expert("tax", "税务专家", "税收", null, null, null);
        Map<String, Object> m = RunService.expertProfileMap(e, null);
        assertFalse(m.containsKey("system_prompt"));
        assertFalse(m.containsKey("knowledge_scope"));
        assertEquals("tax", m.get("key"));
        assertEquals("税务专家", m.get("name"));
        assertEquals("税收", m.get("summary"));
    }

    @Test
    @DisplayName("tags / recs 原样带出")
    void tagsAndRecsCarried() {
        AiExpert e = expert("labor", "劳动专家", "劳动", "intro",
                List.of((Object) "劳动合同", (Object) "工伤"),
                List.of((Object) "如何签合同", (Object) "离职补偿"));
        ExpertSettings s = settings("劳动法专家。", null);
        Map<String, Object> m = RunService.expertProfileMap(e, s);
        assertEquals(List.of((Object) "劳动合同", (Object) "工伤"), m.get("tags"));
        assertEquals(List.of((Object) "如何签合同", (Object) "离职补偿"), m.get("recs"));
    }

    @Test
    @DisplayName("空 tags / recs 集合时不出现对应键")
    void emptyCollectionsAbsent() {
        AiExpert e = expert("ip", "知产专家", null, null, List.of(), List.of());
        ExpertSettings s = settings("知产专家。", null);
        Map<String, Object> m = RunService.expertProfileMap(e, s);
        assertFalse(m.containsKey("tags"), "空 tags 集合不应出现键");
        assertFalse(m.containsKey("recs"), "空 recs 集合不应出现键");
    }

    @Test
    @DisplayName("null AiExpert 返回空 Map")
    void nullExpertEmptyMap() {
        Map<String, Object> m = RunService.expertProfileMap(null, settings("x", null));
        assertTrue(m.isEmpty());
    }
}
