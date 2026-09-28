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

    /**
     * 平台「调整某租户资源上限」用：取租户主体做存在性 + 回执名称。
     *
     * <p>2026-09-28：本方法原为 V66 批次 A 的 {@code selectTenantWithHierarchy}（多带
     * {@code parent_id} / {@code level} 两列，供子租户层级使用）。子租户能力已按用户决定移除，
     * 层级列随之在 V68 中删除，方法体只保留仍然在用的「登录域名」列。</p>
     */
    @Select("SELECT id, tenant_id AS tenantId, code, name, status, domain FROM sys_tenant "
            + "WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Map<String, Object> selectTenantWithHierarchy(@Param("id") Long id);

    @Select("SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Map<String, Object> selectUser(@Param("id") Long id);

    @Select("SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NULL AND username = #{username} LIMIT 1")
    Map<String, Object> selectUserByUsername(@Param("username") String username);

    /**
     * 查同名的「已软删」账号。username 上有唯一键，软删行仍然占位，
     * 因此重建机构 / 复用同名管理员时必须先复活旧行，否则 INSERT 撞唯一键直接 500。
     */
    @Select("SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NOT NULL AND username = #{username} "
            + "ORDER BY id DESC LIMIT 1")
    Map<String, Object> selectDeletedUserByUsername(@Param("username") String username);

    /** 复活软删账号：清 deleted_at，并按下发信息复位归属 / 昵称 / 联系方式 / 口令 / 启用态。 */
    @Update("UPDATE sys_user SET deleted_at = NULL, tenant_id = #{tenantId}, nickname = #{nickname}, "
            + "mobile = #{mobile}, email = #{email}, password_hash = #{passwordHash}, "
            + "status = 'ENABLED' WHERE id = #{id}")
    int reviveUser(@Param("id") Long id, @Param("tenantId") Long tenantId,
                   @Param("nickname") String nickname, @Param("mobile") String mobile,
                   @Param("email") String email, @Param("passwordHash") String passwordHash);

    @Select("SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NULL AND tenant_id = #{tenantId} "
            + "ORDER BY id")
    List<Map<String, Object>> selectUsersOfTenant(@Param("tenantId") Long tenantId);

    /**
     * 按 id 集合批量取账号 —— 员工名册列表补「账号」列用。
     *
     * <p>员工列表此前直接回吐 {@code org_member} 实体，而账号只存在于 {@code sys_user}，
     * 于是列表页「账号」列恒空。逐行查会 N+1，故一次 IN 取回。</p>
     */
    @Select("<script>SELECT id, tenant_id AS tenantId, username, nickname, mobile, email, status "
            + "FROM sys_user WHERE deleted_at IS NULL AND id IN "
            + "<foreach collection='ids' item='i' open='(' separator=',' close=')'>#{i}</foreach>"
            + "</script>")
    List<Map<String, Object>> selectUsersByIds(@Param("ids") List<Long> ids);

    /**
     * 本租户的账号清单（V67 / docs/38 批次 C 的「绑定账号」候选）。
     *
     * <p>为什么不用平台的 {@code /admin/users}：那是平台管理员专用，
     * 租户管理员取不到；而「给员工绑定账号」恰恰是租户/机构管理员的日常动作。</p>
     *
     * <p>{@code boundMemberName} 为 NULL ⇒ 该账号**没有绑定任何员工**，即规格里说的
     * 「虚拟管理员账号」——服务层据此回吐 {@code virtual:true}，不另加 is_virtual 列。</p>
     */
    @Select("<script>SELECT u.id, u.username, u.nickname, u.status, "
            + "(SELECT m.name FROM org_member_account a "
            + "  JOIN org_member m ON m.id = a.member_id AND m.deleted_at IS NULL "
            + "  WHERE a.user_id = u.id AND a.deleted_at IS NULL ORDER BY a.is_primary DESC, a.id LIMIT 1) "
            + "  AS boundMemberName "
            + "FROM sys_user u WHERE u.deleted_at IS NULL AND u.tenant_id = #{tenantId} "
            + "<if test='keyword != null and keyword != \"\"'>"
            + "AND (u.username LIKE CONCAT('%', #{keyword}, '%') "
            + "  OR u.nickname LIKE CONCAT('%', #{keyword}, '%'))</if> "
            + "ORDER BY u.id LIMIT 200</script>")
    List<Map<String, Object>> selectTenantAccounts(@Param("tenantId") Long tenantId,
                                                   @Param("keyword") String keyword);

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

    /**
     * 复活被软删的角色绑定，返回影响行数（0 = 没有可复活的软删行）。
     *
     * <p>与 {@code sys_user.username} 同型缺陷：{@code uk_sys_user_role(user_id, role_id)} 是**普通唯一键**，
     * 软删行仍然占位；而 {@link #selectUserRole} 带 {@code deleted_at IS NULL} ⇒ 查不到，于是直接
     * INSERT 会撞唯一键抛 500。现场复现：移除员工（{@code deleteMember} 会 revokeRole 软删该行）后，
     * 再用**同一账号**新增员工 ⇒ 500 Duplicate entry。</p>
     */
    @Update("UPDATE sys_user_role SET deleted_at = NULL, created_by = #{createdBy}, "
            + "updated_at = NOW(6) WHERE deleted_at IS NOT NULL "
            + "AND user_id = #{userId} AND role_id = #{roleId}")
    int reviveUserRole(@Param("userId") Long userId, @Param("roleId") Long roleId,
                       @Param("createdBy") Long createdBy);

    /** 新建账号（企业管理员交接 / 批量导出入驻时自动开户）。 */
    @Insert("INSERT INTO sys_user (tenant_id, username, password_hash, nickname, mobile, email, "
            + "status, auth_type, created_by) VALUES (#{tenantId}, #{username}, #{passwordHash}, "
            + "#{nickname}, #{mobile}, #{email}, 'ENABLED', 'local', #{createdBy})")
    @org.apache.ibatis.annotations.Options(useGeneratedKeys = true, keyProperty = "id")
    int insertUser(Map<String, Object> row);

    /** 重置登录口令（按 userId）。返回 0 = 账号不存在。 */
    @Update("UPDATE sys_user SET password_hash = #{passwordHash}, updated_at = NOW(6) "
            + "WHERE id = #{userId} AND deleted_at IS NULL")
    int updateUserPassword(@Param("userId") Long userId, @Param("passwordHash") String passwordHash);

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

    /**
     * 机构授权目录可选的数字员工。
     *
     * <p><b>必须带 tenantId</b>：此前无参且不过滤租户，返回全表 200 条里的全部租户行，
     * 租户 2 的授权下拉里因此出现租户 3 的数字员工（实测 11 条 = t0 3 + t2 4 + t3 4）。
     * 这与 docs/15 §八「tenant_id 只从 JWT 取」相悖，且选中即构成跨租户授权。
     * 口径与 {@link #selectExperts} 保持一致，只是数字员工没有「平台公共资产」一说
     * （平台样板走 {@code is_template=1} 且由模板端点复制，不进授权目录）。</p>
     */
    @Select("SELECT id, tenant_id AS tenantId, name, status FROM agent_worker "
            + "WHERE deleted_at IS NULL AND tenant_id = #{tenantId} ORDER BY id LIMIT 200")
    List<Map<String, Object>> selectWorkers(@Param("tenantId") Long tenantId);

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

    @Insert("INSERT INTO approval_order (tenant_id, user_id, applicant_name, applicant_type, "
            + "applicant_department_id, biz_type, title, content, "
            + "form_data, attachment, status, created_at, created_by) VALUES (#{tenantId}, #{userId}, "
            + "#{applicantName}, COALESCE(#{applicantType}, 'USER'), #{applicantDepartmentId}, "
            + "#{bizType}, #{title}, #{content}, #{formData}, #{attachment}, "
            + "'PENDING', NOW(6), #{createdBy})")
    @org.apache.ibatis.annotations.Options(useGeneratedKeys = true, keyProperty = "id")
    int insertApprovalOrder(Map<String, Object> row);

    @Update("UPDATE approval_order SET status = #{status}, approver = #{approver}, "
            + "decision_note = #{note}, decided_at = NOW(6), updated_at = NOW(6) WHERE id = #{id}")
    int updateApprovalOrderStatus(@Param("id") Long id, @Param("status") String status,
                                  @Param("approver") String approver, @Param("note") String note);

    @Select("SELECT o.id, o.tenant_id AS tenantId, o.user_id AS userId, o.applicant_name AS applicantName, "
            + "o.applicant_type AS applicantType, o.applicant_department_id AS applicantDepartmentId, "
            + "(SELECT d.name FROM org_department d WHERE d.id = o.applicant_department_id) AS applicantDepartmentName, "
            + "o.biz_type AS bizType, o.title, o.content, o.form_data AS formData, o.attachment, o.status, "
            + "o.approver, o.decision_note AS decisionNote, o.decided_at AS decidedAt, o.created_at AS createdAt, "
            + "o.parent_order_id AS parentOrderId, o.parent_task_id AS parentTaskId "
            + "FROM approval_order o WHERE o.deleted_at IS NULL AND o.id = #{id} LIMIT 1")
    Map<String, Object> selectApprovalOrder(@Param("id") Long id);

    /**
     * 子流程回指父单据 —— 六期（V60）。
     *
     * <p>为什么不在 insert 时带上：子单据是复用既有 {@code submit()} 建出来的，
     * 那一条链路不该为一个调用方多带两个参数。建完再回指，父链路零改动。</p>
     */
    @Update("UPDATE approval_order SET parent_order_id = #{parentOrderId}, parent_task_id = #{parentTaskId}, "
            + "updated_at = NOW(6) WHERE id = #{id}")
    int updateApprovalOrderParent(@Param("id") Long id, @Param("parentOrderId") Long parentOrderId,
                                  @Param("parentTaskId") Long parentTaskId);

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
    @Select("SELECT o.id, o.tenant_id AS tenantId, o.user_id AS userId, o.applicant_name AS applicantName, "
            + "o.applicant_type AS applicantType, o.applicant_department_id AS applicantDepartmentId, "
            + "(SELECT d.name FROM org_department d WHERE d.id = o.applicant_department_id) AS applicantDepartmentName, "
            + "o.biz_type AS bizType, o.title, o.content, o.form_data AS formData, o.attachment, o.status, "
            + "o.approver, o.decision_note AS decisionNote, o.decided_at AS decidedAt, o.created_at AS createdAt "
            + "FROM approval_order o WHERE o.deleted_at IS NULL AND o.tenant_id = #{tenantId} "
            + "AND o.user_id = #{userId} ORDER BY o.id DESC LIMIT 200")
    List<Map<String, Object>> selectApprovalOrdersOfUser(@Param("tenantId") Long tenantId,
                                                         @Param("userId") Long userId);

    /**
     * 「本部门名义发起的申请」（E-10）—— 部门成员对本部门主体单据的只读可见性。
     *
     * <p>二期让部门能以自己的名义发起审批，但可见范围只到提交人（部门正职）与审批人，
     * 部门成员在系统里看不到「我所在部门提过什么」—— 而这是部门申请这一能力应有的含义。
     * 本查询把它补上：只按<b>精确部门</b>匹配，不含子部门（子部门是另一件事，
     * 「本部门」在用户认知里就是自己那一格）。</p>
     *
     * <p>带 {@code tenant_id} 条件：即便部门 id 全局唯一，也避免任何跨租户串读的可能。</p>
     */
    @Select("SELECT o.id, o.tenant_id AS tenantId, o.user_id AS userId, o.applicant_name AS applicantName, "
            + "o.applicant_type AS applicantType, o.applicant_department_id AS applicantDepartmentId, "
            + "(SELECT d.name FROM org_department d WHERE d.id = o.applicant_department_id) AS applicantDepartmentName, "
            + "o.biz_type AS bizType, o.title, o.content, o.form_data AS formData, o.attachment, o.status, "
            + "o.approver, o.decision_note AS decisionNote, o.decided_at AS decidedAt, o.created_at AS createdAt "
            + "FROM approval_order o WHERE o.deleted_at IS NULL AND o.tenant_id = #{tenantId} "
            + "AND o.applicant_type = 'DEPARTMENT' AND o.applicant_department_id = #{departmentId} "
            + "ORDER BY o.id DESC LIMIT 200")
    List<Map<String, Object>> selectDeptSubjectOrdersOfDept(@Param("tenantId") Long tenantId,
                                                            @Param("departmentId") Long departmentId);

    /** 单据当前待审节点（seq 最小的 PENDING 任务）——「当前流转到谁」。 */
    @Select("SELECT t.id, t.seq, t.approver_type AS approverType, t.approver_id AS approverId, "
            + "t.approver_name AS approverName, t.status FROM approval_task t "
            + "WHERE t.order_id = #{orderId} AND t.status = 'PENDING' AND t.task_role = 'APPROVE' "
            + "ORDER BY t.seq ASC LIMIT 1")
    Map<String, Object> selectCurrentTaskOfOrder(@Param("orderId") Long orderId);

    /**
     * 单据的「审批链」（按 seq 升序）——流转路径。
     *
     * <p><b>刻意排除知会节点</b>（{@code task_role='CC'}）：流转路径回答的是
     * 「这一单要经谁批准、现在轮到谁」，把抄送条目混进来会让「有效节点数」失真
     * （用户端与验收都会按节点数判断审批层级）。知会条目走
     * {@link #selectCcTasksOfUser(Long)}，二者是两条不同的用户界面。</p>
     */
    @Select("SELECT t.id, t.tenant_id AS tenantId, t.seq, t.approver_type AS approverType, "
            + "t.approver_id AS approverId, t.node_mode AS nodeMode, t.node_duty AS nodeDuty, "
            + "t.approver_name AS approverName, t.status, t.note, t.skip_reason AS skipReason, "
            + "t.decided_at AS decidedAt FROM approval_task t "
            + "WHERE t.order_id = #{orderId} AND t.task_role = 'APPROVE' ORDER BY t.seq ASC, t.id ASC")
    List<Map<String, Object>> selectTasksOfOrder(@Param("orderId") Long orderId);

    /**
     * 单据审批评级数（不含知会节点）——「共 N 级」。
     *
     * <p>按 <b>distinct seq</b> 计而非任务条数：五期的会签 / 抢占会把一个节点展开成同 seq 的
     * 多条任务，若按条数计，一个「三人会签」节点会被报成 3 级，与流转路径显示的级次矛盾。
     * 对单人模式（改造前后的全部既有流程）二者恒等。</p>
     */
    @Select("SELECT COUNT(DISTINCT seq) FROM approval_task WHERE order_id = #{orderId} AND task_role = 'APPROVE'")
    long countTasksOfOrder(@Param("orderId") Long orderId);

    /**
     * 「抄送我的」——知会 / 待阅清单（对标 O2OA 的「待阅」）。
     *
     * <p>一级审批后机构管理员不再出现在审批链上，但必须能看到成员申请（可督办）。
     * 这里返回他收到的知会条目（带单据摘要），供用户端「抄送我的」分区展示。</p>
     */
    @Select("SELECT t.id AS taskId, t.order_id AS orderId, t.seq, t.approver_type AS approverType, "
            + "t.approver_name AS approverName, t.created_at AS ccAt, t.cc_read_at AS readAt, "
            + "o.tenant_id AS tenantId, o.user_id AS userId, o.applicant_name AS applicantName, "
            + "o.applicant_type AS applicantType, o.applicant_department_id AS applicantDepartmentId, "
            + "(SELECT d.name FROM org_department d WHERE d.id = o.applicant_department_id) AS applicantDepartmentName, "
            + "o.biz_type AS bizType, o.title, o.content, o.form_data AS formData, o.attachment, "
            + "o.status AS status, o.approver, o.decision_note AS decisionNote, "
            + "o.decided_at AS decidedAt, o.created_at AS createdAt "
            + "FROM approval_task t JOIN approval_order o ON o.id = t.order_id "
            + "WHERE t.deleted_at IS NULL AND o.deleted_at IS NULL "
            + "AND t.task_role = 'CC' AND t.approver_id = #{userId} "
            + "ORDER BY t.id DESC LIMIT 200")
    List<Map<String, Object>> selectCcTasksOfUser(@Param("userId") Long userId);

    /** 单条知会任务（判定归属与角色用）：不存在返回 null；软删行不返回。 */
    @Select("SELECT id, order_id AS orderId, tenant_id AS tenantId, approver_id AS approverId, "
            + "task_role AS taskRole, cc_read_at AS readAt FROM approval_task "
            + "WHERE id = #{id} AND deleted_at IS NULL LIMIT 1")
    Map<String, Object> selectCcTask(@Param("id") Long id);

    /**
     * 标记知会条目已读 —— <b>幂等</b>：仅在未读（{@code cc_read_at IS NULL}）时写一次，
     * 重复调用时间<b>不倒退</b>（C-04）。
     */
    @Update("UPDATE approval_task SET cc_read_at = #{now}, updated_at = NOW(6) "
            + "WHERE id = #{id} AND task_role = 'CC' AND cc_read_at IS NULL")
    int markCcRead(@Param("id") Long id, @Param("now") java.time.LocalDateTime now);

    /**
     * 我的未读知会条数（C-06 {@code ccUnread}）—— 与 {@link #countMyCcTasks} 同集合，
     * 仅多一个 {@code cc_read_at IS NULL} 条件；{@code summary.cc} 语义不变（总条数）。
     */
    @Select("SELECT COUNT(*) FROM approval_task t JOIN approval_order o ON o.id = t.order_id "
            + "WHERE t.deleted_at IS NULL AND o.deleted_at IS NULL "
            + "AND t.task_role = 'CC' AND t.approver_id = #{userId} AND t.cc_read_at IS NULL")
    long countMyUnreadCcTasks(@Param("userId") Long userId);

    /**
     * 置某单据推给某人的站内通知已读（C-09：点开知会 → 联动置通知已读）。
     * 仅未读通知（{@code read_at IS NULL}）被改写，幂等安全。
     */
    @Update("UPDATE notification SET read_at = NOW(6), updated_at = NOW(6) "
            + "WHERE deleted_at IS NULL AND user_id = #{userId} AND ref_id = #{orderId} "
            + "AND read_at IS NULL")
    int markNotificationsReadOfOrder(@Param("userId") Long userId, @Param("orderId") Long orderId);

    /** 「抄送我的」条数（知会不阻塞流转，故与待办计数完全分账）。 */
    @Select("SELECT COUNT(*) FROM approval_task t JOIN approval_order o ON o.id = t.order_id "
            + "WHERE t.deleted_at IS NULL AND o.deleted_at IS NULL "
            + "AND t.task_role = 'CC' AND t.approver_id = #{userId}")
    long countMyCcTasks(@Param("userId") Long userId);

    /**
     * 「待我处理」条数 —— 与 {@code ApprovalFlowService.todo()} <b>同口径</b>，只是不下发明细。
     *
     * <p>四个条件必须同时满足，缺一会算错：</p>
     * <ol>
     *   <li>{@code approver_id = 我}：指派给我；</li>
     *   <li>{@code t.status = 'PENDING'}：我这一级未处理；</li>
     *   <li><b>我是该单据 seq 最小的 PENDING 节点</b>：只有「当前节点」才轮到我 ——
     *       否则一条三级单据会同时点亮二级、三级审批人的红点；</li>
     *   <li>{@code o.status = 'PENDING'}：单据未终态（排除被驳回/撤销后残留的 PENDING 任务）。</li>
     * </ol>
     *
     * <p>知会（{@code task_role='CC'}）节点状态为 {@code CC} 而非 PENDING，天然被排除；
     * 仍显式声明 {@code task_role='APPROVE'} 以免日后有人把知会改成 PENDING 时静默污染待办。</p>
     */
    @Select("SELECT COUNT(*) FROM approval_task t JOIN approval_order o ON o.id = t.order_id "
            + "WHERE t.deleted_at IS NULL AND t.status = 'PENDING' AND t.approver_id = #{userId} "
            + "AND t.task_role = 'APPROVE' "
            + "AND o.deleted_at IS NULL AND o.status = 'PENDING' "
            + "AND t.seq = (SELECT MIN(t2.seq) FROM approval_task t2 "
            + "            WHERE t2.order_id = t.order_id AND t2.status = 'PENDING' "
            + "            AND t2.task_role = 'APPROVE' AND t2.deleted_at IS NULL)")
    long countMyTodoTasks(@Param("userId") Long userId);

    /** 「我发起的、仍在途」的单据数（红点旁边的次级信息，不参与审批人提醒）。 */
    @Select("SELECT COUNT(*) FROM approval_order WHERE deleted_at IS NULL "
            + "AND user_id = #{userId} AND status = 'PENDING'")
    long countMyPendingOrders(@Param("userId") Long userId);

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
    @org.apache.ibatis.annotations.Options(useGeneratedKeys = true, keyProperty = "id")
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

    /**
     * 资源授权页「知识库」类型的可选目录。
     *
     * <p>与 {@link #selectUnboundKb} 的两点差异，都是刻意的：</p>
     * <ul>
     *   <li>只要 {@code scope = 'TENANT'}（租户共享）。本方法服务于「把资料授权给某个机构」，
     *       而 {@code PERSONAL} 是**他人个人**上传的资料 —— 让租户管理员在授权下拉里看到它，
     *       等于开了一条「把别人的个人资料挂进机构」的路。</li>
     *   <li>列名用 {@code name}（前端授权目录行读的是 {@code r.name}），不是 {@code docName}。</li>
     * </ul>
     */
    @Select("SELECT id, doc_name AS name, scope, state, chunk_count AS chunkCount, size_bytes AS sizeBytes, "
            + "created_at AS createdAt FROM kb_document WHERE deleted_at IS NULL "
            + "AND tenant_id IN (0, #{tenantId}) AND institution_id = 0 AND scope = 'TENANT' "
            + "ORDER BY id DESC LIMIT 200")
    List<Map<String, Object>> selectGrantableKb(@Param("tenantId") Long tenantId);

    /**
     * 资料在本租户（含平台级 tenant_id=0）内的显示名；不存在 / 已删除 / 属其它租户 → {@code null}。
     *
     * <p>授权与机构挂载的前置校验用。为什么要单独问一次、而不是拿 {@code bindKbDocument} 的影响行数
     * 当判据：MySQL 对「SET 值与现值相同」的 UPDATE 报 <b>0 行</b>，于是「重复保存同一条授权」会被
     * 误判成「资料不存在」而 404。返回名称顺带解决了挂载时账本行需要 res_name 的问题。</p>
     */
    @Select("SELECT doc_name FROM kb_document WHERE deleted_at IS NULL AND id = #{id} "
            + "AND tenant_id IN (0, #{tenantId}) LIMIT 1")
    String selectKbNameInTenant(@Param("id") Long id, @Param("tenantId") Long tenantId);

    /**
     * 资料当前归属的机构 id（0 = 未挂载，在租户共享库）。
     *
     * <p>为什么必须问这一句：{@code kb_document.institution_id} 是**单值**列 ——
     * 一条资料同时只能属于一个机构。于是「把资料授权给机构 B」在资料已属于机构 A 时，
     * 实际动作是**把它从 A 搬走**。若不拦，跨租户就会出现「B 租户静默搬走 A 租户机构的资料」，
     * 且 A 侧那条授权记录会变成幽灵行（清单说已启用、资料却不在自己机构里）。</p>
     */
    @Select("SELECT institution_id FROM kb_document WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Long selectKbInstitutionId(@Param("id") Long id);

    @Select("SELECT COUNT(*) FROM leave_request WHERE deleted_at IS NULL "
            + "AND institution_id = #{institutionId} AND status = #{status}")
    long countLeaveByStatus(@Param("institutionId") Long institutionId, @Param("status") String status);

    @Select("SELECT COUNT(*) FROM org_department WHERE deleted_at IS NULL "
            + "AND institution_id = #{institutionId} AND status = 'ACTIVE'")
    long countActiveDepts(@Param("institutionId") Long institutionId);

    @Select("SELECT COUNT(*) FROM org_member WHERE deleted_at IS NULL "
            + "AND institution_id = #{institutionId} AND status = 'ACTIVE'")
    long countActiveMembers(@Param("institutionId") Long institutionId);

    /**
     * 本租户会话总数（V63 用户端首页「本组织数据」租户口径用）。
     *
     * <p>与机构/部门口径同源：都是对 {@code chat_conversation} 计数，
     * 差别只在 user_id 的归属集合。口径同源才有可比性 —— 否则「机构数加起来不等于租户数」，
     * 看板自身就自相矛盾。</p>
     */
    @Select("SELECT COUNT(*) FROM chat_conversation "
            + "WHERE deleted_at IS NULL AND tenant_id = #{tenantId}")
    long countConversationsOfTenant(@Param("tenantId") Long tenantId);
}
