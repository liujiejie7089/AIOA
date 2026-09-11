package cn.aioa.resource.support;

/**
 * 数字员工角色类型 —— 职责边界与所需权限的**唯一定义源**。
 *
 * <p>三张表共同构成权限模型，任何一处判定都必须回到本枚举，不得在业务代码里散写字符串：</p>
 * <pre>
 *   WorkerRole（类型） --requiredPermission--> PermissionCatalog（权限码） --roles--> 允许的角色
 * </pre>
 *
 * <p>职责边界 = {@link #duty()}，会被拼进会话的系统提示，用于限定 AI 只回答职责范围内的问题；
 * 所需权限 = {@link #requiredPermission()}，用于「创建/承担该类型数字人角色」的准入校验。</p>
 */
public enum WorkerRole {

    /** 通用办公助手：默认类型，无额外权限要求。 */
    GENERAL("通用办公助手", "通用办公问答、文案撰写与信息整理", PermissionCatalog.CHAT_BASIC),

    /** 请假审批数字人：受理请假申请、校验证明材料、按请假制度送审与答复。 */
    LEAVE_APPROVER("请假审批数字人",
            "受理请假申请、校验请假类型与证明材料、按请假制度给出送审与答复意见",
            PermissionCatalog.APPROVAL_LEAVE),

    /** 知识库问答数字人：只依据企业知识库检索结果作答。 */
    KB_ASSISTANT("知识库问答数字人",
            "基于企业知识库检索企业制度与资料，据实作答并标注引用来源",
            PermissionCatalog.KB_READ),

    /** 公文起草数字人：起草对外/对内公文。 */
    DOC_DRAFTER("公文起草数字人",
            "起草通知、请示、报告、函等公文，遵循公文格式规范",
            PermissionCatalog.DOC_DRAFT);

    private final String displayName;
    private final String duty;
    private final String requiredPermission;

    WorkerRole(String displayName, String duty, String requiredPermission) {
        this.displayName = displayName;
        this.duty = duty;
        this.requiredPermission = requiredPermission;
    }

    public String code() {
        return name();
    }

    public String displayName() {
        return displayName;
    }

    public String duty() {
        return duty;
    }

    public String requiredPermission() {
        return requiredPermission;
    }

    /** 宽松解析：未知/空值一律降级为 {@link #GENERAL}，避免历史数据或前端传错直接 500。 */
    public static WorkerRole of(String code) {
        if (code == null || code.isBlank()) {
            return GENERAL;
        }
        for (WorkerRole role : values()) {
            if (role.name().equalsIgnoreCase(code.trim())) {
                return role;
            }
        }
        return GENERAL;
    }

    /**
     * 由名称/职责描述推断类型（仅用于创建时未显式指定类型的兜底）。
     * 命中关键词才升级为专用类型，否则为 {@link #GENERAL}。
     */
    public static WorkerRole infer(String name, String description) {
        String text = (name == null ? "" : name) + " " + (description == null ? "" : description);
        if (text.contains("请假") || text.contains("休假") || text.contains("考勤")) {
            return LEAVE_APPROVER;
        }
        if (text.contains("知识库") || text.contains("检索") || text.contains("制度问答")) {
            return KB_ASSISTANT;
        }
        if (text.contains("公文") || text.contains("通知") || text.contains("请示") || text.contains("报告")) {
            return DOC_DRAFTER;
        }
        return GENERAL;
    }
}
