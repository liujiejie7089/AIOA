package cn.aioa.org.mapper;

import cn.aioa.org.entity.OrgFeedback;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * 投诉与建议 mapper（V63）。
 *
 * <p>除 CRUD（{@link BaseMapper}）外，这里只放「接收人解析」需要的四个查询。
 * 它们刻意写成独立的窄查询而不是复用 {@code OrgGuard} —— 原因：</p>
 * <ul>
 *   <li>{@code OrgGuard} 的方法都建立在 {@code AuthUserContext}（当前登录人）之上，
 *       而接收人解析的输入是「<b>提交人</b>所属部门」，两者不是一回事：管理员代录、
 *       或未来由定时任务兜底重派时，调用方都不是提交人本人。</li>
 *   <li>解析顺序本身是业务规则（本部门 → 本机构 → 租户），
 *       放在一处由 {@code FeedbackService} 显式串起来，比隐含在 guard 里可读。</li>
 * </ul>
 */
@Mapper
public interface OrgFeedbackMapper extends BaseMapper<OrgFeedback> {

    // ==================== 接收人解析（逐级上溯） ====================

    /**
     * 第一级：部门负责人 —— {@code org_department.leader_user_id}。
     *
     * <p>只取启用部门；部门已停用时不认（停用部门的负责人不该继续收反馈）。</p>
     */
    @Select("SELECT leader_user_id FROM org_department "
            + "WHERE id = #{departmentId} AND deleted_at IS NULL AND status = 'ACTIVE' "
            + "AND leader_user_id IS NOT NULL LIMIT 1")
    Long selectDeptLeaderUserId(@Param("departmentId") Long departmentId);

    /**
     * 第一级回落：部门内持有「部门正职」职务的在职成员。
     *
     * <p>与 {@code OrgGuard.requireDeptLeader} 同口径（{@code duty_code='DEPT_PRINCIPAL'}），
     * 因为「谁是部门负责人」这件事在整个系统里只能有一个答案。
     * {@code job_title} 是自由文本展示字段，绝不作为依据。</p>
     */
    @Select("SELECT user_id FROM org_member "
            + "WHERE department_id = #{departmentId} AND duty_code = 'DEPT_PRINCIPAL' "
            + "AND deleted_at IS NULL AND status = 'ACTIVE' ORDER BY id LIMIT 1")
    Long selectDeptPrincipalUserId(@Param("departmentId") Long departmentId);

    /**
     * 第二级：机构管理员 —— 本机构 {@code is_org_admin=1} 的在职成员。
     *
     * <p>取 id 最小的那一位，保证同一机构下结果<b>确定</b>（否则同一份反馈可能派给不同人，
     * 排查时无法复现）。</p>
     */
    @Select("SELECT user_id FROM org_member "
            + "WHERE institution_id = #{institutionId} AND is_org_admin = 1 "
            + "AND deleted_at IS NULL AND status = 'ACTIVE' ORDER BY id LIMIT 1")
    Long selectInstitutionAdminUserId(@Param("institutionId") Long institutionId);

    // ==================== 统计（本组织数据卡） ====================

    /** 本部门在职成员数。 */
    @Select("SELECT COUNT(*) FROM org_member WHERE deleted_at IS NULL AND status = 'ACTIVE' "
            + "AND department_id = #{departmentId}")
    long countMembersOfDept(@Param("departmentId") Long departmentId);

    /** 本部门直接下级部门数（不含更深层级 —— 「下属部门」在用户认知里就是直接那层）。 */
    @Select("SELECT COUNT(*) FROM org_department WHERE deleted_at IS NULL AND status = 'ACTIVE' "
            + "AND parent_id = #{departmentId}")
    long countChildDepts(@Param("departmentId") Long departmentId);

    /** 本部门范围内知识库文档数。 */
    @Select("SELECT COUNT(*) FROM kb_document WHERE deleted_at IS NULL AND department_id = #{departmentId}")
    long countKbOfDept(@Param("departmentId") Long departmentId);

    /** 本部门范围内会话数（按提交/使用者归属部门归集）。 */
    @Select("SELECT COUNT(*) FROM chat_conversation c WHERE c.deleted_at IS NULL "
            + "AND c.tenant_id = #{tenantId} AND c.user_id IN "
            + "(SELECT m.user_id FROM org_member m WHERE m.deleted_at IS NULL AND m.institution_id = #{institutionId})")
    long countConversationsOfInstitution(@Param("tenantId") Long tenantId,
                                         @Param("institutionId") Long institutionId);

    /** 本部门范围内会话数。 */
    @Select("SELECT COUNT(*) FROM chat_conversation c WHERE c.deleted_at IS NULL "
            + "AND c.tenant_id = #{tenantId} AND c.user_id IN "
            + "(SELECT m.user_id FROM org_member m WHERE m.deleted_at IS NULL AND m.department_id = #{departmentId})")
    long countConversationsOfDept(@Param("tenantId") Long tenantId,
                                  @Param("departmentId") Long departmentId);

    /** 本部门本月词元消耗（口径同 {@code sumLedgerTokensOfInstitution}，只是把机构换成部门）。 */
    @Select("SELECT COALESCE(SUM(l.total_tokens), 0) FROM token_ledger l "
            + "JOIN org_member m ON m.user_id = l.user_id AND m.department_id = #{departmentId} "
            + "AND m.deleted_at IS NULL "
            + "WHERE l.deleted_at IS NULL AND l.tenant_id = #{tenantId} "
            + "AND DATE_FORMAT(l.created_at, '%Y-%m') = #{period}")
    long sumLedgerTokensOfDept(@Param("tenantId") Long tenantId,
                               @Param("departmentId") Long departmentId,
                               @Param("period") String period);

    /** 本租户在职成员总数（含未归属部门的成员）。 */
    @Select("SELECT COUNT(*) FROM org_member WHERE deleted_at IS NULL AND status = 'ACTIVE' "
            + "AND tenant_id = #{tenantId}")
    long countMembersOfTenant(@Param("tenantId") Long tenantId);

    /** 本租户启用部门总数。 */
    @Select("SELECT COUNT(*) FROM org_department WHERE deleted_at IS NULL AND status = 'ACTIVE' "
            + "AND tenant_id = #{tenantId}")
    long countDeptsOfTenant(@Param("tenantId") Long tenantId);

    /** 本租户启用机构总数。 */
    @Select("SELECT COUNT(*) FROM org_institution WHERE deleted_at IS NULL AND status = 'ACTIVE' "
            + "AND tenant_id = #{tenantId}")
    long countInstitutionsOfTenant(@Param("tenantId") Long tenantId);

    // ==================== 列表查询 ====================

    /**
     * 我提交过的反馈（含答复）—— 按时间倒序。
     *
     * <p>匿名记录在这里<b>照常返回提交人视角的完整信息</b>：匿名是对上级匿名，
     * 不是对自己匿名。</p>
     */
    @Select("SELECT * FROM org_feedback WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "AND submitter_user_id = #{userId} ORDER BY id DESC LIMIT 200")
    java.util.List<OrgFeedback> selectMine(@Param("tenantId") Long tenantId,
                                           @Param("userId") Long userId);

    /**
     * 派给我的反馈（「收到的建议」）—— 按状态 + 时间倒序。
     *
     * @param status 可空：只看某状态；为空则全部
     */
    @Select("<script>SELECT * FROM org_feedback WHERE deleted_at IS NULL "
            + "AND tenant_id = #{tenantId} AND assignee_user_id = #{userId} "
            + "<if test='status != null'> AND status = #{status} </if> "
            + "ORDER BY (status = 'PENDING') DESC, id DESC LIMIT 200</script>")
    java.util.List<OrgFeedback> selectMyInbox(@Param("tenantId") Long tenantId,
                                              @Param("userId") Long userId,
                                              @Param("status") String status);

    /** 我收到但还没回复的条数（红点）。 */
    @Select("SELECT COUNT(*) FROM org_feedback WHERE deleted_at IS NULL "
            + "AND tenant_id = #{tenantId} AND assignee_user_id = #{userId} AND status = 'PENDING'")
    long countMyPending(@Param("tenantId") Long tenantId, @Param("userId") Long userId);
}
