package cn.aioa.project.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 项目数字人 / 上下文 功能所需的**窄接口**：只读引用其它域的既有对象
 * （{@code agent_worker} / {@code sys_file} / {@code kb_document}），不改它们任何一列。
 *
 * <p><b>为什么不直接依赖 {@code aioa-resource} 的 Mapper</b>：PM 域与「数字员工」域是并列的两个域，
 * 引用既有对象只需要「读 id + 展示字段」。自带一段只读 SQL 可避免引入模块依赖（防环）、
 * 也避免碰对方的实体序列化面（那面已被其自有套件钉住）。同 {@link PmRepoBindMapper} 的取舍
 * （docs/43 §5.1「复用而非重造」）。</p>
 *
 * <p><b>纪律</b>：只读；写 {@code agent_worker} 的路径永远走「数字员工」域自己的接口。</p>
 */
@Mapper
public interface PmAiRefMapper {

    /**
     * 本租户**可分配**的数字员工候选：非全局模板、未删除、已启用的已审通过项。
     *
     * <p>{@code institutionId} 非空时收窄到「本机构 + 租户级（{@code institution_id IS NULL}）」——
     * 与「数字员工」域的可见性口径一致（企业管理员只能管本机构，租户级由全租户共享）。</p>
     */
    @Select("""
            <script>
            SELECT id, name, worker_type, status, enabled, institution_id, icon
              FROM agent_worker
             WHERE tenant_id = #{tenantId}
               AND deleted_at IS NULL
               AND is_template = 0
               AND enabled = 1
               AND audit_status = 'APPROVED'
            <if test="institutionId != null">
               AND (institution_id = #{institutionId} OR institution_id IS NULL)
            </if>
             ORDER BY id DESC
            </script>
            """)
    List<Map<String, Object>> listAssignableWorkers(@Param("tenantId") Long tenantId,
                                                    @Param("institutionId") Long institutionId);

    /** 单个数字员工（校验归属与存在性；已删返回 null）。 */
    @Select("""
            SELECT id, name, worker_type, status, enabled, institution_id
              FROM agent_worker
             WHERE tenant_id = #{tenantId} AND id = #{workerId} AND deleted_at IS NULL
            """)
    Map<String, Object> findWorker(@Param("tenantId") Long tenantId, @Param("workerId") Long workerId);

    /** 单文件的原始文件名（{@code sys_file}）；不存在/已删返回 null，兼作存在性校验。 */
    @Select("""
            SELECT original_name FROM sys_file
             WHERE tenant_id = #{tenantId} AND id = #{fileId} AND deleted_at IS NULL
            """)
    String fileOriginalName(@Param("tenantId") Long tenantId, @Param("fileId") Long fileId);

    /**
     * 单文件的字节数（{@code sys_file.size}）；不存在/已删返回 null。
     *
     * <p>用途：{@code pm_document.size_bytes} 的**唯一事实源**。字节的真实大小只有 {@code sys_file} 知道，
     * 不能依赖调用方（前端）传 {@code sizeBytes} —— 两端各存一份必然漂移
     * （2026-10-10 实测：前端不传该字段，服务端却把它当必填拆箱 ⇒ 上传文档 100% 500）。
     * 后端能查到就自己查。</p>
     */
    @Select("""
            SELECT `size` FROM sys_file
             WHERE tenant_id = #{tenantId} AND id = #{fileId} AND deleted_at IS NULL
            """)
    Long fileSize(@Param("tenantId") Long tenantId, @Param("fileId") Long fileId);

    /** 政策文档名（{@code kb_document}）；不存在/已删返回 null，兼作存在性校验。 */
    @Select("""
            SELECT doc_name FROM kb_document
             WHERE tenant_id = #{tenantId} AND id = #{docId} AND deleted_at IS NULL
            """)
    String kbDocName(@Param("tenantId") Long tenantId, @Param("docId") Long docId);
}
