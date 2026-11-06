package cn.aios.resource.service;

import cn.aios.common.exception.BizException;
import cn.aios.resource.entity.KbChunk;
import cn.aios.resource.entity.KbDocument;
import cn.aios.resource.store.KbRelationalDao;
import cn.aios.resource.store.KnowledgeStore;
import cn.aios.resource.support.GradeSheetExtractor;
import cn.aios.resource.support.MarkdownTable;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 知识库资料（FR-F）：上传入库 → 切片 → 检索 → 引用溯源。
 * state 三态：WAIT 解析中 / OK 已入库 / FAILED 失败（可重试）。
 * 检索命中返回原文片段，经工具网关回传 agent，落 message.completed.citations（FR-D5）。
 *
 * <p>存储物理实现委托 {@link KnowledgeStore}（SPI）：现阶段为 MySQL 实现（LIKE 检索），
 * 后续切换向量数据库只需提供新实现类并配置 {@code aios.kb.store=vector}，
 * 本类、工具网关、管理端/用户端与已接入的业务系统均零改动。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KbService {

    /** 单个切片的最大字符数，超长按此长度二次切分（默认，可被专家配置 chunkSize 覆盖）。 */
    private static final int CHUNK_SIZE = 500;

    /** 切分重叠字符数（默认）。 */
    private static final int CHUNK_OVERLAP = 50;

    /** 可见范围：个人（仅本人可见）。 */
    public static final String SCOPE_PERSONAL = "PERSONAL";
    /** 可见范围：租户共享（同租户全员可见、可被全员检索）。 */
    public static final String SCOPE_TENANT = "TENANT";

    private final KnowledgeStore store;
    private final KbRelationalDao relationalDao;
    private final EmbeddingProvider embeddingProvider;

    /**
     * 当前用户可见的资料：本人资料 + 公共资源（user_id=0）+ 本租户共享（scope=TENANT）。
     * 跨租户数据零泄露（FR-B3）。可见性规则由存储实现保证，与物理实现无关。
     */
    public List<KbDocument> list(Long tenantId, Long userId) {
        return store.listVisible(tenantId, userId);
    }

    /** 按主键读取一条资料（控制器做权限校验前先拿到实体）。 */
    public KbDocument findOne(Long docId) {
        return store.findDocById(docId);
    }

    /** 管理端运营视角：租户内全部资料（不按归属人过滤），调用方需校验 ROLE_ADMIN。 */
    public List<KbDocument> listTenant(Long tenantId) {
        return store.listTenant(tenantId);
    }

    /** 带原文片段的检索结果，供工具网关 citations 与用户端检索测试使用。 */
    public List<KnowledgeStore.KbHit> searchHits(Long tenantId, Long userId, String keyword, int limit) {
        return store.search(tenantId, userId, keyword, limit);
    }

    /** 当前生效的存储实现（mysql / milvus）——供运维排查与 E2E 双跑矩阵判断档位。 */
    public String storeType() {
        return store.type();
    }

    /** 当前生效的嵌入 provider 标识（local / http:模型名）。 */
    public String embeddingProviderName() {
        return embeddingProvider.name();
    }

    /** 当前嵌入维度（必须与 Milvus 集合维度一致）。 */
    public int embeddingDims() {
        return embeddingProvider.dims();
    }

    /**
     * 混合检索（带参数，方案 P2 / B5）：topK / threshold / mode / kbScope 全部真实生效。
     *
     * @param docIdScope 知识库范围（kbScope）：null/空=ALL，否则逗号分隔文档ID已解析为 List
     */
    public List<KnowledgeStore.KbHit> search(Long tenantId, Long userId, String query,
                                             int topK, double threshold, String mode,
                                             List<Long> docIdScope) {
        float[] queryVec = embeddingProvider.embed(query);
        return store.search(tenantId, userId, query, queryVec, topK, threshold, mode, docIdScope);
    }

    /**
     * 登记并入库一份资料：携带正文则同步切片入库并置 OK；无正文置 WAIT 等待异步解析。
     * 切片异常置 FAILED 并记录原因，用户端可重试。
     */
    public KbDocument register(Long tenantId, Long userId, String docName, String icon,
                               Long sizeBytes, String content, String scope) {
        KbDocument doc = new KbDocument();
        doc.setTenantId(tenantId == null ? 0L : tenantId);
        doc.setUserId(userId == null ? 0L : userId);
        doc.setDocName(docName);
        doc.setIcon(icon == null || icon.isBlank() ? guessIcon(docName) : icon);
        doc.setState(KbDocument.STATE_WAIT);
        doc.setSizeBytes(sizeBytes == null
                ? (long) (content == null ? 0 : content.getBytes().length) : sizeBytes);
        doc.setContent(content);
        doc.setScope(normalizeScope(scope));
        doc.setStage(KbDocument.STAGE_PARSING);
        doc.setProgress(0);
        doc.setRetryCount(0);
        doc.setCreatedAt(LocalDateTime.now());
        doc.setCreatedBy(userId);
        store.saveDocument(doc);
        if (content != null && !content.isBlank()) {
            index(doc);
        }
        return doc;
    }

    /** 兼容旧签名（仅登记元信息）。 */
    public KbDocument register(Long tenantId, Long userId, String docName, String icon, Long sizeBytes) {
        return register(tenantId, userId, docName, icon, sizeBytes, null, null);
    }

    /** 切片入库：成功置 OK 并回填切片数，失败置 FAILED 并记录原因。 */
    public KbDocument index(KbDocument doc) {
        return index(doc, CHUNK_SIZE, CHUNK_OVERLAP);
    }

    /**
     * 切片 + 向量化入库（方案 P2 / A4 / B5）。
     *
     * <p>流程：切分（chunkSize/chunkOverlap 可配置）→ 写切片 → 逐个向量化 →
     * 置 OK 并回填切片数；任一步异常置 FAILED 并留痕，可重试。</p>
     */
    public KbDocument index(KbDocument doc, int chunkSize, int chunkOverlap) {
        try {
            // 拍平表格还原（docs/75）：PDF 成绩单是「四栏并排 + 表头拆两行 + 汇总标签行与数值行
            // 分居两行」，取文本后列结构全丢，切片只剩「栏名」或只剩「数字」。这里先还原成
            // Markdown 表并**回写正文**（kb_table_query 读的也是 content 字段），
            // 使 PDF 与 Excel 共用同一条下游（列名分块 / 统计摘要 / 聚合查询）。
            String enriched = GradeSheetExtractor.enrich(doc.getContent());
            if (!enriched.equals(doc.getContent())) {
                doc.setContent(enriched);
                log.info("资料 {} 已还原为结构化成绩表（追加 Markdown 明细与汇总）", doc.getId());
            }
            // 表格感知切分（docs/74 P0-1）：每块带「《doc》/sheet｜列: a/b/c｜」前缀
            List<String> chunks = new ArrayList<>(
                    split(doc.getContent(), chunkSize, chunkOverlap, doc.getDocName()));
            if (chunks.isEmpty()) {
                throw new IllegalArgumentException("正文为空，无法入库");
            }
            // 统计摘要块置首位（docs/74 P0-2）：回答「共有多少条 / 分类各多少」。
            // 必须排在切片 0，检索命中后可被优先注入；正文块整体后移一位。
            List<String> stats = statsChunks(doc.getDocName(), doc.getContent());
            if (!stats.isEmpty()) {
                List<String> merged = new ArrayList<>(stats);
                merged.addAll(chunks);
                chunks = merged;
            }
            int count = store.replaceChunks(doc, chunks);
            // 落库自检（docs/74 P2）：声明值与实际行数不一致 = 「列表看着已索引、检索永远 0 条」，
            // 这种状态原先完全静默，只有用户发现「AI 说没有」时才会暴露。
            int actual = relationalDao.chunksOfDoc(doc.getId()).size();
            if (actual != count) {
                throw new IllegalStateException(
                        "切片落库不完整（声明 " + count + " / 实际 " + actual + "），请重试入库");
            }
            embedAll(doc.getId(), doc.getTenantId(), chunks);
            doc.setState(KbDocument.STATE_OK);
            doc.setChunkCount(count);
            doc.setErrorMsg(null);
            doc.setStage(KbDocument.STAGE_OK);
            doc.setProgress(100);
            doc.setChunkSize(chunkSize);
            doc.setChunkOverlap(chunkOverlap);
            doc.setIndexedAt(LocalDateTime.now());
        } catch (Exception e) {
            doc.setState(KbDocument.STATE_FAILED);
            doc.setStage(KbDocument.STAGE_FAILED);
            doc.setErrorMsg(e.getMessage() == null ? "入库失败" : e.getMessage());
        }
        doc.setUpdatedAt(LocalDateTime.now());
        store.updateDocument(doc);
        return doc;
    }

    /**
     * 为一篇文档里的每张表格生成一块统计摘要（docs/74 P0-2）。
     *
     * <p>为什么必须有：topK 默认 5，1241 行的表即使用完美检索也只覆盖 5 行 ——
     * 拿 5 行明细去回答「共有多少条」是结构性不可能。摘要块把「行数 + 低基数列的分组计数」
     * 压成一块，让聚合类问题第一次就有答案。</p>
     */
    private List<String> statsChunks(String docName, String content) {
        List<String> out = new ArrayList<>();
        for (MarkdownTable.Table t : MarkdownTable.parse(content, docName)) {
            String text = MarkdownTable.statsText(docName, t);
            if (!text.isEmpty()) {
                out.add(text);
            }
        }
        return out;
    }

    /** 对切片逐条向量化并回写（失败不中断整体，仅记录日志，检索时自动退化关键词）。 */
    private void embedAll(Long docId, Long tenantId, List<String> chunks) {
        List<KbChunk> rows = relationalDao.chunksOfDoc(docId);
        for (int i = 0; i < rows.size() && i < chunks.size(); i++) {
            KbChunk c = rows.get(i);
            try {
                float[] vec = embeddingProvider.embed(chunks.get(i));
                store.saveEmbedding(c.getId(), chunks.get(i), vec, embeddingProvider.name(), embeddingProvider.dims());
            } catch (Exception e) {
                log.warn("切片向量化失败 chunkId={}: {}", c.getId(), e.getMessage());
            }
        }
    }

    /**
     * 用**当前** embedding provider 全量重算切片向量（docs/32 Ph1「重算 job」）。
     *
     * <p>触发场景：{@code aios.kb.embedding-provider} 从 {@code local} 换成 {@code http}、
     * 或换了 embedding 模型 / 维度。**不重算的后果是静默的**——
     * 旧向量维度与新 query 向量不符，{@link EmbeddingProvider#cosine} 直接返回 0，
     * 检索「不出错但永远不命中」。</p>
     *
     * <p>幂等：只处理 {@code embedding_provider} 或 {@code embedding_dims} 与当前 provider 不符的切片，
     * 已是最新的跳过；单条失败只告警、继续下一条（与 {@link #embedAll} 一致，便于分批重跑收敛）。</p>
     *
     * @return 实际重算条数
     */
    public int reembedAll() {
        final int batchSize = 200;
        final String wantProvider = embeddingProvider.name();
        final int wantDims = embeddingProvider.dims();
        long cursor = 0L;
        int done = 0;
        int scanned = 0;
        while (true) {
            List<KbChunk> batch = relationalDao.chunksAfterId(cursor, batchSize);
            if (batch.isEmpty()) {
                break;
            }
            for (KbChunk c : batch) {
                cursor = Math.max(cursor, c.getId());
                scanned++;
                if (wantProvider.equals(c.getEmbeddingProvider())
                        && c.getEmbeddingDims() != null && c.getEmbeddingDims() == wantDims) {
                    continue;
                }
                try {
                    float[] vec = embeddingProvider.embed(c.getContent());
                    store.saveEmbedding(c.getId(), c.getContent(), vec, wantProvider, wantDims);
                    done++;
                } catch (Exception e) {
                    log.warn("切片重算向量失败 chunkId={}: {}", c.getId(), e.getMessage());
                }
            }
            if (batch.size() < batchSize) {
                break;
            }
        }
        log.info("知识库向量全量重算完成：扫描={} 重算={} provider={} dims={}", scanned, done, wantProvider, wantDims);
        return done;
    }

    /** 失败重试：重新切片入库。 */
    public KbDocument retry(Long docId) {
        KbDocument doc = store.findDocById(docId);
        if (doc == null) {
            throw BizException.notFound("资料不存在：" + docId);
        }
        if (doc.getContent() == null || doc.getContent().isBlank()) {
            doc.setState(KbDocument.STATE_FAILED);
            doc.setStage(KbDocument.STAGE_FAILED);
            doc.setErrorMsg("资料无正文内容，请重新上传");
            doc.setUpdatedAt(LocalDateTime.now());
            store.updateDocument(doc);
            return doc;
        }
        doc.setRetryCount((doc.getRetryCount() == null ? 0 : doc.getRetryCount()) + 1);
        return index(doc);
    }

    /** 修改资料元信息：重命名与可见范围（PERSONAL / TENANT）。 */
    public KbDocument update(Long docId, String name, String scope) {
        KbDocument doc = store.findDocById(docId);
        if (doc == null) {
            throw BizException.notFound("资料不存在：" + docId);
        }
        if (name != null && !name.isBlank()) {
            doc.setDocName(name.trim());
        }
        if (scope != null && !scope.isBlank()) {
            doc.setScope(normalizeScope(scope));
        }
        doc.setUpdatedAt(LocalDateTime.now());
        store.updateDocument(doc);
        return doc;
    }

    /** 删除资料（逻辑删除文档与切片）。 */
    public void remove(Long docId) {
        store.deleteDocument(docId);
    }

    /** 用户端自助检索测试（FR-F3 配套）：返回原文片段。 */
    public List<KnowledgeStore.KbHit> searchMine(Long tenantId, Long userId, String keyword, int limit) {
        return searchHits(tenantId, userId, keyword, limit);
    }

    /** 按段落切分：先按换行分段，超长段按 chunkSize 二次切分（带 chunkOverlap 重叠）。 */
    static List<String> split(String content) {
        return split(content, CHUNK_SIZE, CHUNK_OVERLAP);
    }

    /** 带参数的切分：chunkSize 为单块字符数，chunkOverlap 为相邻块重叠字符数。 */
    static List<String> split(String content, int chunkSize, int chunkOverlap) {
        return split(content, chunkSize, chunkOverlap, null);
    }

    /**
     * 带文档名的切分：**表格走「列名 + 连续 N 行」**，其余按段落切（docs/74 P0-1）。
     *
     * <p>原实现按 {@code \n} 切段、单段 ≤ chunkSize 直接成块，而 Excel 转 Markdown 后
     * <b>每个数据行都以 {@code \n} 结尾</b> ⇒ 表格被切成「一行一块」：500 行的表切出 503 块，
     * 其中带列名的只有 1 块（表头那块，还常被 {@code ### Sheet1} 挤开）。模型看到
     * {@code | 1 | 川剧 | 传统技艺 | 成都市 | 第六批 |} 并不知道哪列是"批次"。</p>
     *
     * <p>改法：解析出表格区间后<b>原位替换</b>为该表的「列名前缀 + 连续数据行」块；
     * 紧贴表格上方的 {@code ### sheetName} 标题不再单独成块（信息已并入前缀）。</p>
     *
     * <p><b>2026-11-06 追加（docs/76）</b>：非表格内容原先是「一行一块」（{@code p.length() <= size}
     * 就直接成块），于是 PDF 取出的 1800 字正文变成 <b>38 块</b>，每块只有 4 门课、没有列名 ——
     * 命中也没法用，还挤掉真正的表格块。现在改为<b>按段落合并</b>：累积到 {@code size} 才落盘，
     * 空行与 Markdown 标题作为段落边界。同一份 PDF 由 38 块降到 3~4 块。</p>
     */
    static List<String> split(String content, int chunkSize, int chunkOverlap, String docName) {
        List<String> out = new ArrayList<>();
        if (content == null) {
            return out;
        }
        int size = chunkSize <= 0 ? CHUNK_SIZE : chunkSize;
        int overlap = Math.max(0, Math.min(chunkOverlap, size / 2));
        String normalized = content.replace("\r", "");
        String[] lines = normalized.split("\n", -1);
        List<MarkdownTable.Table> tables = MarkdownTable.parse(normalized, docName);
        // 表格占用的行区间 + 需要吞掉的 sheet 标题行（紧邻表格上方一行）
        Set<Integer> consumed = new HashSet<>();
        for (MarkdownTable.Table t : tables) {
            for (int i = t.startLine(); i <= t.endLine(); i++) {
                consumed.add(i);
            }
            int above = t.startLine() - 1;
            if (above >= 0 && above < lines.length && lines[above].trim().startsWith("###")) {
                consumed.add(above);
            }
        }
        int ti = 0;
        StringBuilder buf = new StringBuilder();
        for (int i = 0; i < lines.length; i++) {
            if (consumed.contains(i)) {
                // 表格起点：先把累积的段落落盘，再把整表替换为它的列名块
                flush(buf, out);
                if (ti < tables.size() && tables.get(ti).startLine() == i) {
                    out.addAll(MarkdownTable.chunks(docName, tables.get(ti)));
                    ti++;
                }
                continue;
            }
            String p = lines[i].trim();
            // 空行与 Markdown 标题都是段落边界
            if (p.isEmpty() || p.startsWith("#")) {
                flush(buf, out);
                if (p.isEmpty()) {
                    continue;
                }
            }
            // 累积到 size 再落盘：一行一块会把「1800 字的 PDF 正文」切成 38 块，
            // 每块只有 4 门课、且没有列名 —— 检索命中了也用不上。
            if (buf.length() > 0 && buf.length() + 1 + p.length() > size) {
                flush(buf, out);
            }
            if (buf.length() > 0) {
                buf.append('\n');
            }
            buf.append(p);
            while (buf.length() > size) {
                int step = size - overlap;
                out.add(buf.substring(0, size));
                buf.delete(0, step);
            }
        }
        flush(buf, out);
        return out;
    }

    /** 把累积的段落落盘（空白段直接丢弃）。 */
    private static void flush(StringBuilder buf, List<String> out) {
        String s = buf.toString().trim();
        if (!s.isEmpty()) {
            out.add(s);
        }
        buf.setLength(0);
    }

    private static String normalizeScope(String scope) {
        return SCOPE_TENANT.equalsIgnoreCase(scope) ? SCOPE_TENANT : SCOPE_PERSONAL;
    }

    /** 按文件名后缀猜一个图标，前端可覆盖。 */
    private static String guessIcon(String name) {
        if (name == null) {
            return "doc";
        }
        String lower = name.toLowerCase();
        if (lower.endsWith(".xlsx") || lower.endsWith(".xls") || lower.endsWith(".csv")) {
            return "sheet";
        }
        if (lower.endsWith(".docx") || lower.endsWith(".doc") || lower.endsWith(".txt")) {
            return "doc";
        }
        if (lower.endsWith(".pdf")) {
            return "pdf";
        }
        return "file";
    }
}
