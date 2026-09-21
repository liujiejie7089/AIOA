package cn.aioa.resource.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「嵌入 provider 维度 × Milvus 集合维度」一致性校验单测。
 *
 * <p>锁死的是一类**完全静默**的失效：两个维度分处两个配置键，不一致时接口不报错、
 * 切片也照常入库，只是 Milvus 一条都不进、检索永远无命中。所以这里必须机器强制，
 * 而不是只在文档里写一句「两者必须一致」。</p>
 *
 * <p>同时锁死失败文案的**可操作性**（含实际维度与"该改成什么"），因为运维在目标机上
 * 只有日志可看，文案退化成「维度不一致」就等于没报错。</p>
 */
class MilvusDimGuardTest {

    @Test
    @DisplayName("一致时必须放行（local 256 维 vs 集合 256 维）")
    void agreesWhenEqual() {
        assertDoesNotThrow(() -> MilvusConfig.assertDimsAgree("local", 256, 256, "kb_chunk_v1_256"));
    }

    @Test
    @DisplayName("http provider 与集合维度一致时同样放行")
    void agreesForHttpProvider() {
        assertDoesNotThrow(() -> MilvusConfig.assertDimsAgree("http:bge-small-zh-v1.5", 512, 512, "kb_chunk_v1"));
    }

    @Test
    @DisplayName("回归锁：provider=local（代码固定 256 维）配 milvus.dims=512 必须启动失败")
    void localProviderWith512MustFail() {
        IllegalStateException ex = assertThrows(IllegalStateException.class,
                () -> MilvusConfig.assertDimsAgree("local", 256, 512, "kb_chunk_v1"));
        String msg = ex.getMessage();
        // 必须写出两个实际维度，否则运维不知道是哪个配错了
        assertTrue(msg.contains("256"), "文案应含 provider 实际维度 256：" + msg);
        assertTrue(msg.contains("512"), "文案应含配置的集合维度 512：" + msg);
        // 必须给出 local 专有的修法：改集合名（维度不可改）
        assertTrue(msg.contains("换成一个新名字") || msg.contains("换一个集合名"),
                "local 档应提示换集合名：" + msg);
        // 必须说明不修的后果，避免被当成可以忽略的告警
        assertTrue(msg.contains("静默"), "文案应说明后果是静默失效：" + msg);
    }

    @Test
    @DisplayName("http provider 维度不符时，提示把 milvus.dims 改成 provider 的实际维度")
    void httpProviderMismatchSuggestsProviderDims() {
        IllegalStateException ex = assertThrows(IllegalStateException.class,
                () -> MilvusConfig.assertDimsAgree("http:bge-small-zh-v1.5", 1024, 512, "kb_chunk_v1"));
        String msg = ex.getMessage();
        assertTrue(msg.contains("1024"), "文案应含 provider 实际维度 1024：" + msg);
        assertTrue(msg.contains("改成 1024") || msg.contains("= 1024"),
                "http 档应提示把 milvus.dims 改成 1024：" + msg);
    }

    @Test
    @DisplayName("任一侧维度未知（<=0）时不校验，避免误伤未配置的部署")
    void skipsWhenDimsUnknown() {
        assertDoesNotThrow(() -> MilvusConfig.assertDimsAgree("local", 256, 0, "kb_chunk_v1"));
        assertDoesNotThrow(() -> MilvusConfig.assertDimsAgree("local", 0, 512, "kb_chunk_v1"));
    }

    @Test
    @DisplayName("provider 标识为 null 时不应因文案分支而 NPE")
    void nullProviderNameIsSafe() {
        assertThrows(IllegalStateException.class,
                () -> MilvusConfig.assertDimsAgree(null, 256, 512, "kb_chunk_v1"));
    }
}
