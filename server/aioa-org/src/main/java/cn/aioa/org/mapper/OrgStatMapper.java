package cn.aioa.org.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;
import java.util.Map;

/**
 * 跨域只读/少量写 mapper：企业入驻域需要读取既有系统表与用户端业务表
 * （sys_user / sys_role / sys_user_role / sys_tenant / token_ledger / kb_document /
 *  approval_order / model_config），但不引入对 aioa-admin、aioa-resource 的模块依赖，
 * 以免破坏既有模块边界与构建顺序。
 */
public interface OrgStatMapper {

    // ------------------------------------------------------------------ 租户 / 用户 / 角色

    @Select("SELECT id, tenant_id AS tenantId, code, name, status FROM sys_tenant "
            + "WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Map<String, Object> selectTenant(@Param("id") Long id);

    @Select("SELECT id, tenant_id AS tenantId, code, name, status FROM sys_tenant "
            + "WHERE deleted_at IS NULL ORDER BY id")
    List<Map<String, Object>> selectTenants();

    @Select("SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Map<String, Object> selectUser(@Param("id") Long id);

    @Select("SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NULL AND username = #{username} LIMIT 1")
    Map<String, Object> selectUserByUsername(@Param("username") String username);

    @Select("SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "ORDER BY id")
    List<Map<String, Object>> selectUsersOfTenant(@Param("tenantId") Long tenantId);

    @Select("SELECT r.id, r.role_code AS roleCode, r.name, r.data_scope AS dataScope "
            + "FROM sys_role r WHERE r.deleted_at IS NULL ORDER BY r.id")
    List<Map<String, Object>> selectRoles();

    @Select("SELECT r.id FROM sys_role r WHERE r.deleted_at IS NULL AND r.role_code = #{roleCode} LIMIT 1")
    Long selectRoleIdByCode(@Param("roleCode") String roleCode);

    @Select("SELECT ur.id FROM sys_user_role ur "
            + "WHERE ur.deleted_at IS NULL AND ur.user_id = #{userId} AND ur.role_id = #{roleId} LIMIT 1")
    Long selectUserRole(@Param("userId") Long userId, @Param("roleId") Long roleId);

    @Select("SELECT r.role_code FROM sys_user_role ur JOIN sys_role r ON r.id = ur.role_id "
            + "WHERE ur.deleted_at IS NULL AND r.deleted_at IS NULL AND ur.user_id = #{userId}")
    List<String> selectRoleCodesOfUser(@Param("userId") Long userId);

    @Insert("INSERT INTO sys_user_role (tenant_id, user_id, role_id, created_by) "
            + "VALUES (#{tenantId}, #{userId}, #{roleId}, #{createdBy})")
    int insertUserRole(@Param("tenantId") Long tenantId, @Param("userId") Long userId,
                       @Param("roleId") Long roleId, @Param("createdBy") Long createdBy);

    @Update("UPDATE sys_user_role SET deleted_at = NOW(6) "
            + "WHERE deleted_at IS NULL AND user_id = #{userId} AND role_id = #{roleId}")
    int deleteUserRole(@Param("userId") Long userId, @Param("roleId") Long roleId);

    /** 新建账号（企业管理员交接 / 批量导出入驻时自动开户）。 */
    @Insert("INSERT INTO sys_user (tenant_id, username, password_hash, nickname, mobile, email, "
            + "status, auth_type, created_by) VALUES (#{tenantId}, #{username}, #{passwordHash}, "
            + "#{nickname}, #{mobile}, #{email}, 'ENABLED', 'local', #{createdBy})")
    @org.apache.ibatis.annotations.Options(useGeneratedKeys = true, keyProperty = "id")
    int insertUser(Map<String, Object> row);

    // ------------------------------------------------------------------ 账本 / 分摊核对

    @Select("SELECT COALESCE(SUM(total_tokens), 0) FROM token_ledger "
            + "WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "AND DATE_FORMAT(created_at, '%Y-%m') = #{period}")
    long sumLedgerTokens(@Param("tenantId") Long tenantId, @Param("period") String period);

    @Select("SELECT COALESCE(SUM(l.total_tokens), 0) FROM token_ledger l "
            + "JOIN org_member m ON m.user_id = l.user_id AND m.institution_id = #{institutionId} "
            + "AND m.deleted_at IS NULL "
            + "WHERE l.deleted_at IS NULL AND l.tenant_id = #{tenantId} "
            + "AND DATE_FORMAT(l.created_at, '%Y-%m') = #{period}")
    long sumLedgerTokensOfInstitution(@Param("tenantId") Long tenantId,
                                      @Param("institutionId") Long institutionId,
                                      @Param("period") String period);

    @Select("SELECT l.user_id AS userId, COALESCE(SUM(l.total_tokens), 0) AS tokens "
            + "FROM token_ledger l JOIN org_member m ON m.user_id = l.user_id "
            + "AND m.institution_id = #{institutionId} AND m.deleted_at IS NULL "
            + "WHERE l.deleted_at IS NULL AND l.tenant_id = #{tenantId} "
            + "AND DATE_FORMAT(l.created_at, '%Y-%m') = #{period} GROUP BY l.user_id")
    List<Map<String, Object>> usageByUserOfInstitution(@Param("tenantId") Long tenantId,
                                                       @Param("institutionId") Long institutionId,
                                                       @Param("period") String period);

    // ------------------------------------------------------------------ 知识库 / 审批 / 模型

    @Select("SELECT COUNT(*) FROM kb_document WHERE deleted_at IS NULL "
            + "AND institution_id = #{institutionId}")
    long countKbOfInstitution(@Param("institutionId") Long institutionId);

    @Select("SELECT id, doc_name AS docName, icon, state, scope, department_id AS departmentId, "
            + "chunk_count AS chunkCount, size_bytes AS sizeBytes, error_msg AS errorMsg, "
            + "created_at AS createdAt, indexed_at AS indexedAt "
            + "FROM kb_document WHERE deleted_at IS NULL AND institution_id = #{institutionId} "
            + "ORDER BY id DESC LIMIT 200")
    List<Map<String, Object>> selectKbOfInstitution(@Param("institutionId") Long institutionId);

    @Select("SELECT COUNT(*) FROM approval_order WHERE deleted_at IS NULL "
            + "AND tenant_id = #{tenantId} AND status = 'PENDING'")
    long countPendingApprovals(@Param("tenantId") Long tenantId);

    @Select("SELECT id, provider_key AS providerKey, name, model_name AS modelName, enabled "
            + "FROM model_config ORDER BY sort, id")
    List<Map<String, Object>> selectModelConfigs();

    @Select("SELECT id, provider_key AS providerKey, name, model_name AS modelName, enabled "
            + "FROM model_config WHERE provider_key = #{key} LIMIT 1")
    Map<String, Object> selectModelConfig(@Param("key") String key);

    @Select("SELECT id, name, status FROM agent_worker "
            + "WHERE deleted_at IS NULL ORDER BY id LIMIT 200")
    List<Map<String, Object>> selectWorkers();

    @Select("SELECT id, tenant_id AS tenantId, expert_key AS resKey, name, enabled FROM ai_expert "
            + "WHERE deleted_at IS NULL AND tenant_id IN (0, #{tenantId}) ORDER BY sort, id LIMIT 200")
    List<Map<String, Object>> selectExperts(@Param("tenantId") Long tenantId);

    @Select("SELECT id, tenant_id AS tenantId, skill_name AS resName, expert_key AS parentKey, "
            + "enabled FROM ai_skill WHERE deleted_at IS NULL AND tenant_id IN (0, #{tenantId}) "
            + "ORDER BY sort, id LIMIT 200")
    List<Map<String, Object>> selectSkills(@Param("tenantId") Long tenantId);

    // ------------------------------------------------------------------ 部门内成员个人额度

    // ------------------------------------------------------------------ 部门内成员个人额度

    @Select("SELECT COALESCE(SUM(quota_tokens), 0) FROM tenant_quota "
            + "WHERE deleted_at IS NULL AND tenant_id = #{tenantId} AND user_id IN "
            + "(SELECT user_id FROM org_member WHERE deleted_at IS NULL AND institution_id = #{institutionId})")
    long sumPersonalQuotaOfInstitution(@Param("tenantId") Long tenantId,
                                       @Param("institutionId") Long institutionId);

    // ------------------------------------------------------------------ 审批单 / 通知（多级审批复用既有单据主表）

    @Insert("INSERT INTO approval_order (tenant_id, user_id, applicant_name, biz_type, title, content, "
            + "form_data, attachment, status, created_at, created_by) VALUES (#{tenantId}, #{userId}, "
            + "#{applicantName}, #{bizType}, #{title}, #{content}, #{formData}, #{attachment}, "
            + "'PENDING', NOW(6), #{createdBy})")
    @org.apache.ibatis.annotations.Options(useGeneratedKeys = true, keyProperty = "id")
    int insertApprovalOrder(Map<String, Object> row);

    @Update("UPDATE approval_order SET status = #{status}, approver = #{approver}, "
            + "decision_note = #{note}, decided_at = NOW(6), updated_at = NOW(6) WHERE id = #{id}")
    int updateApprovalOrderStatus(@Param("id") Long id, @Param("status") String status,
                                  @Param("approver") String approver, @Param("note") String note);

    @Select("SELECT id, tenant_id AS tenantId, user_id AS userId, applicant_name AS applicantName, "
            + "biz_type AS bizType, title, content, form_data AS formData, attachment, status, "
            + "approver, decision_note AS decisionNote, decided_at AS decidedAt, created_at AS createdAt "
            + "FROM approval_order WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Map<String, Object> selectApprovalOrder(@Param("id") Long id);

    @Select("<script>SELECT id, tenant_id AS tenantId, user_id AS userId, "
            + "applicant_name AS applicantName, biz_type AS bizType, title, status, "
            + "decision_note AS decisionNote, created_at AS createdAt FROM approval_order "
            + "WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "<if test='userId != null'> AND user_id = #{userId} </if> "
            + "<if test='status != null'> AND status = #{status} </if> "
            + "ORDER BY id DESC LIMIT 200</script>")
    List<Map<String, Object>> selectApprovalOrders(@Param("tenantId") Long tenantId,
                                                   @Param("userId") Long userId,
                                                   @Param("status") String status);

    /**
     * 「我发起的」全字段列表（含 form_data / attachment）。
     *
     * <p>与 {@link #selectApprovalOrders} 的区别：后者只取列表页需要的窄字段，
     * 用户端「我的申请」详情要回显请假表单与附件，因此必须带全字段。</p>
     */
    @Select("SELECT id, tenant_id AS tenantId, user_id AS userId, applicant_name AS applicantName, "
            + "biz_type AS bizType, title, content, form_data AS formData, attachment, status, "
            + "approver, decision_note AS decisionNote, decided_at AS decidedAt, created_at AS createdAt "
            + "FROM approval_order WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "AND user_id = #{userId} ORDER BY id DESC LIMIT 200")
    List<Map<String, Object>> selectApprovalOrdersOfUser(@Param("tenantId") Long tenantId,
                                                         @Param("userId") Long userId);

    /** 单据当前待审节点（seq 最小的 PENDING 任务）——「当前流转到谁」。 */
    @Select("SELECT t.id, t.seq, t.approver_type AS approverType, t.approver_id AS approverId, "
            + "t.approver_name AS approverName, t.status FROM approval_task t "
            + "WHERE t.order_id = #{orderId} AND t.status = 'PENDING' "
            + "ORDER BY t.seq ASC LIMIT 1")
    Map<String, Object> selectCurrentTaskOfOrder(@Param("orderId") Long orderId);

    /** 单据全部节点（按 seq 升序）——流转路径。 */
    @Select("SELECT t.id, t.seq, t.approver_type AS approverType, t.approver_id AS approverId, "
            + "t.approver_name AS approverName, t.status, t.note, t.skip_reason AS skipReason, "
            + "t.decided_at AS decidedAt FROM approval_task t "
            + "WHERE t.order_id = #{orderId} ORDER BY t.seq ASC")
    List<Map<String, Object>> selectTasksOfOrder(@Param("orderId") Long orderId);

    @Select("SELECT COUNT(*) FROM approval_task WHERE order_id = #{orderId}")
    long countTasksOfOrder(@Param("orderId") Long orderId);

    @Select("SELECT u.id FROM sys_user_role ur JOIN sys_role r ON r.id = ur.role_id "
            + "JOIN sys_user u ON u.id = ur.user_id "
            + "WHERE ur.deleted_at IS NULL AND r.deleted_at IS NULL AND u.deleted_at IS NULL "
            + "AND u.status = 'ENABLED' AND u.tenant_id = #{tenantId} AND r.role_code = #{roleCode} "
            + "ORDER BY u.id LIMIT 1")
    Long selectFirstUserIdOfRole(@Param("tenantId") Long tenantId, @Param("roleCode") String roleCode);

    @Select("SELECT id, COALESCE(nickname, username) AS name FROM sys_user "
            + "WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Map<String, Object> selectUserName(@Param("id") Long id);

    @Insert("INSERT INTO notification (tenant_id, user_id, type, title, content, ref_id, created_at) "
            + "VALUES (#{tenantId}, #{userId}, #{type}, #{title}, #{content}, #{refId}, NOW(6))")
    int insertNotification(Map<String, Object> row);

    @Select("<script>SELECT COUNT(*) FROM audit_log WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "<if test='institutionId != null'> AND institution_id = #{institutionId} </if></script>")
    long countAuditLogs(@Param("tenantId") Long tenantId,
                        @Param("institutionId") Long institutionId);

    @Select("<script>SELECT id, institution_id AS institutionId, scope, action, resource_type AS resourceType, "
            + "resource_id AS resourceId, summary, actor_name AS actorName, actor_role AS actorRole, "
            + "result, detail, `before` AS beforeJson, `after` AS afterJson, "
            + "created_at AS createdAt FROM audit_log "
            + "WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "<if test='institutionId != null'> AND institution_id = #{institutionId} </if> "
            + "ORDER BY id DESC LIMIT #{limit}</script>")
    List<Map<String, Object>> selectAuditLogs(@Param("tenantId") Long tenantId,
                                              @Param("institutionId") Long institutionId,
                                              @Param("limit") int limit);

    // ------------------------------------------------------------------ 机构知识库（FR-I）

    // 租户可引入的共享库 = 本租户共享资料 + 平台级（tenant_id=0）共享资料。
    // 注意：仍严格排除其它租户的资料，跨租户可见性不被放开。
    @Update("UPDATE kb_document SET institution_id = #{institutionId}, department_id = #{departmentId}, "
            + "scope = #{scope}, updated_at = NOW(6) "
            + "WHERE id = #{id} AND tenant_id IN (0, #{tenantId}) AND deleted_at IS NULL")
    int bindKbDocument(@Param("id") Long id, @Param("tenantId") Long tenantId,
                       @Param("institutionId") Long institutionId,
                       @Param("departmentId") Long departmentId,
                       @Param("scope") String scope);

    @Update("UPDATE kb_document SET state = #{state}, error_msg = #{errorMsg}, updated_at = NOW(6) "
            + "WHERE id = #{id} AND institution_id = #{institutionId} AND deleted_at IS NULL")
    int reviewKbDocument(@Param("id") Long id, @Param("institutionId") Long institutionId,
                         @Param("state") String state, @Param("errorMsg") String errorMsg);

    @Select("SELECT id, doc_name AS docName, state, scope, user_id AS userId, size_bytes AS sizeBytes, "
            + "chunk_count AS chunkCount, institution_id AS institutionId, department_id AS departmentId, "
            + "created_at AS createdAt FROM kb_document WHERE deleted_at IS NULL "
            + "AND tenant_id IN (0, #{tenantId}) AND institution_id = 0 "
            + "AND scope IN ('TENANT', 'PERSONAL') ORDER BY id DESC LIMIT 200")
    List<Map<String, Object>> selectUnboundKb(@Param("tenantId") Long tenantId);

    @Select("SELECT COUNT(*) FROM leave_request WHERE deleted_at IS NULL "
            + "AND institution_id = #{institutionId} AND status = #{status}")
    long countLeaveByStatus(@Param("institutionId") Long institutionId, @Param("status") String status);

    @Select("SELECT COUNT(*) FROM org_department WHERE deleted_at IS NULL "
            + "AND institution_id = #{institutionId} AND status = 'ACTIVE'")
    long countActiveDepts(@Param("institutionId") Long institutionId);

    @Select("SELECT COUNT(*) FROM org_member WHERE deleted_at IS NULL "
            + "AND institution_id = #{institutionId} AND status = 'ACTIVE'")
    long countActiveMembers(@Param("institutionId") Long institutionId);
}
