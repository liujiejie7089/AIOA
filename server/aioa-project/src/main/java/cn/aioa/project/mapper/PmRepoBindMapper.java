package cn.aioa.project.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;
import java.util.Map;

/**
 * 项目 ↔ 代码仓库绑定的**窄接口**（只碰 {@code gitee_project.pm_project_id} 一列）。
 *
 * <p><b>为什么不复用 {@code GiteeProjectMapper} / 不给 {@code GiteeProject} 加字段</b>：
 * {@code aioa-gitee} 是已验收 116 项的既有域（V48）。给它的实体加字段会改变它的响应序列化面，
 * 而那 116 项断言正是钉在这个面上的 —— 一个纯新增字段不该有回归风险。
 * 故本模块自带一段只读写 {@code pm_project_id} 的 SQL，**gitee 域一行不改**（最小改动 = 零回归）。</p>
 *
 * <p><b>BR-06 的唯一性靠 SQL 原子保证</b>：{@link #bind} 的 WHERE 条件带
 * {@code pm_project_id IS NULL}，一个仓库只有一次从 NULL 被绑走的机会；
 * 并发下第二次绑定影响行数为 0，服务层据此判 409「仓库已归属其它项目」，
 * 而不是先查后写（先查后写在并发下会双双成功）。</p>
 */
@Mapper
public interface PmRepoBindMapper {

    /** 项目下已绑定的仓库（含仓库基本信息，供详情页「仓库」页签渲染）。 */
    @Select("""
            SELECT id, name, repo_name, gitee_owner, gitee_repo, gitee_html_url,
                   default_branch, status, error_msg, pm_project_id
              FROM gitee_project
             WHERE tenant_id = #{tenantId} AND pm_project_id = #{projectId} AND deleted_at IS NULL
             ORDER BY id
            """)
    List<Map<String, Object>> listByProject(@Param("tenantId") Long tenantId,
                                            @Param("projectId") Long projectId);

    /**
     * 可被绑定的仓库候选：本租户内**尚未归属任何项目**且非创建失败/已删除的仓库。
     *
     * <p>只回 {@code ACTIVE}：{@code CREATING} 的仓库还没建完，绑上去会让项目看起来「有仓库但打不开」；
     * {@code FAILED} 的应先重试建仓再绑。</p>
     */
    @Select("""
            SELECT id, name, repo_name, gitee_owner, gitee_repo, gitee_html_url, default_branch, status
              FROM gitee_project
             WHERE tenant_id = #{tenantId} AND pm_project_id IS NULL
               AND deleted_at IS NULL AND status = 'ACTIVE'
             ORDER BY id DESC
            """)
    List<Map<String, Object>> listBindable(@Param("tenantId") Long tenantId);

    /** 单个仓库（含绑定归属），用于「这个仓库归谁」的校验与回显。 */
    @Select("""
            SELECT id, name, repo_name, gitee_owner, gitee_repo, gitee_html_url, default_branch,
                   status, error_msg, pm_project_id
              FROM gitee_project
             WHERE tenant_id = #{tenantId} AND id = #{repoId} AND deleted_at IS NULL
            """)
    Map<String, Object> findRepo(@Param("tenantId") Long tenantId, @Param("repoId") Long repoId);

    /**
     * 绑定仓库到项目。**影响行数为 0 = 该仓库已被别的项目绑走**（或不存在 / 已删）。
     *
     * @return 受影响行数（0 或 1）
     */
    @Update("""
            UPDATE gitee_project
               SET pm_project_id = #{projectId}, updated_at = NOW(6)
             WHERE tenant_id = #{tenantId} AND id = #{repoId}
               AND deleted_at IS NULL AND pm_project_id IS NULL
            """)
    int bind(@Param("tenantId") Long tenantId, @Param("repoId") Long repoId,
             @Param("projectId") Long projectId);

    /**
     * 解绑（只置空，**不删仓库记录**，BR-06）。
     *
     * @return 受影响行数
     */
    @Update("""
            UPDATE gitee_project
               SET pm_project_id = NULL, updated_at = NOW(6)
             WHERE tenant_id = #{tenantId} AND id = #{repoId} AND pm_project_id = #{projectId}
               AND deleted_at IS NULL
            """)
    int unbind(@Param("tenantId") Long tenantId, @Param("repoId") Long repoId,
               @Param("projectId") Long projectId);

    /** 项目已绑仓库数（BR-02 判「DEV→BUSINESS 是否可改」的依据之一）。 */
    @Select("""
            SELECT COUNT(*) FROM gitee_project
             WHERE tenant_id = #{tenantId} AND pm_project_id = #{projectId} AND deleted_at IS NULL
            """)
    long countBound(@Param("tenantId") Long tenantId, @Param("projectId") Long projectId);

    /** 项目下带仓库信息的任务数（BR-02 的另一半依据：有任务带仓库 ⇒ 不能改回业务项目）。 */
    @Select("""
            SELECT COUNT(*) FROM pm_task
             WHERE tenant_id = #{tenantId} AND project_id = #{projectId}
               AND deleted_at IS NULL AND repo_id IS NOT NULL
            """)
    long countTasksWithRepo(@Param("tenantId") Long tenantId, @Param("projectId") Long projectId);
}
