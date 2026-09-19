package cn.aioa.resource.service;

import cn.aioa.resource.config.KbProperties;
import cn.aioa.resource.store.KnowledgeStore;
import cn.aioa.resource.store.MilvusKnowledgeStore;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * 知识库索引维护启动任务（docs/32：Ph1 的「全量重算」与 Ph2 的「回填 job」）。
 *
 * <p>两个开关互不耦合，可单独使用，且**默认全关**——不配就什么都不做，
 * 保证既有环境（mysql 档位）启动行为零变化：</p>
 * <ul>
 *   <li>{@code aioa.kb.reembed-on-start} —— 用当前 embedding provider 重算所有切片向量。
 *       换 provider / 换模型后跑一次；</li>
 *   <li>{@code aioa.kb.milvus.backfill-on-start} —— 把 MySQL 切片灌入 Milvus（首次接入 / 索引重建）。</li>
 * </ul>
 *
 * <p>顺序有意为「先重算、后回填」：回填读的就是 MySQL 里的向量 BLOB，
 * 必须先保证 BLOB 是当前 provider 产的，否则会把旧维度的向量灌进新集合（白跑一次）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class KbIndexMaintenanceRunner implements ApplicationRunner {

    private final KbProperties props;
    private final KbService kbService;
    private final KnowledgeStore store;

    @Override
    public void run(ApplicationArguments args) {
        if (props.isReembedOnStart()) {
            long t0 = System.currentTimeMillis();
            log.info("启动任务[向量全量重算] 开始：store={} provider={}", store.type(), props.getEmbeddingProvider());
            int n = kbService.reembedAll();
            log.info("启动任务[向量全量重算] 完成：重算 {} 条，耗时 {} ms", n, System.currentTimeMillis() - t0);
        }

        if (props.getMilvus().isBackfillOnStart()) {
            if (store instanceof MilvusKnowledgeStore milvusStore) {
                long t0 = System.currentTimeMillis();
                log.info("启动任务[Milvus 索引回填] 开始：collection={}",
                        props.getMilvus().getCollection());
                int n = milvusStore.backfill();
                log.info("启动任务[Milvus 索引回填] 完成：写入 {} 条，耗时 {} ms", n, System.currentTimeMillis() - t0);
            } else {
                log.warn("aioa.kb.milvus.backfill-on-start=true 但当前 store={} 不是 milvus，已忽略（避免误灌索引）",
                        store.type());
            }
        }
    }
}
