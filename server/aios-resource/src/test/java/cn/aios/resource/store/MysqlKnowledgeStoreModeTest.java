package cn.aios.resource.store;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 检索模式归一化（docs/75）。
 *
 * <p>回归的是一类「静默 0 命中」：模式认不出时关键词与向量两路都不打分，
 * 融合结果为空，调用方拿到 {@code ok:true, data:[]}，最后表现为「库里有资料却检索不到」。
 * 最常见的触发方式是**不传 mode** —— {@code String.valueOf(null)} 会得到字符串 {@code "null"}。</p>
 */
class MysqlKnowledgeStoreModeTest {

    @Test
    @DisplayName("三种合法模式原样保留（大小写与空格无关）")
    void keepsValidModes() {
        assertEquals("bm25", MysqlKnowledgeStore.normalizeMode("bm25"));
        assertEquals("vector", MysqlKnowledgeStore.normalizeMode(" VECTOR "));
        assertEquals("hybrid", MysqlKnowledgeStore.normalizeMode("Hybrid"));
    }

    @Test
    @DisplayName("null / 空白 → hybrid（默认两路都跑）")
    void defaultsToHybrid() {
        assertEquals("hybrid", MysqlKnowledgeStore.normalizeMode(null));
        assertEquals("hybrid", MysqlKnowledgeStore.normalizeMode("   "));
    }

    @Test
    @DisplayName("字符串 \"null\" 与拼错的模式都退回 hybrid，绝不返回空模式")
    void unknownFallsBackToHybrid() {
        assertEquals("hybrid", MysqlKnowledgeStore.normalizeMode("null"));
        assertEquals("hybrid", MysqlKnowledgeStore.normalizeMode("keyword"));
        assertEquals("hybrid", MysqlKnowledgeStore.normalizeMode("bm2"));
    }
}
