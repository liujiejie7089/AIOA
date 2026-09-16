package cn.aioa.resource.support;

import cn.aioa.security.PermissionCatalog;

import java.util.List;

/**
 * 数字员工角色类型 —— 职责边界与所需权限的**唯一定义源**。
 *
 * <p>三张表共同构成权限模型，任何一处判定都必须回到本枚举，不得在业务代码里散写字符串：</p>
 * <pre>
 *   WorkerRole（类型） --requiredPermission--> PermissionCatalog（权限码） --roles--> 允许的角色
 * </pre>
 *
 * <p>职责边界 = {@link #duty()}（能做什么），反向边界 = {@link #boundary()}（不做什么）；
 * 二者一并会被拼进会话的系统提示，用于限定 AI 只回答职责范围内的问题。
 * 所需权限 = {@link #requiredPermission()}，用于「创建/承担该类型数字人角色」的准入校验；
 * 所需能力 = {@link #requiredTools()}，用于创建前的<b>能力前置检查</b>
 * （区分「平台没有这个能力」与「你没有这个权限」，两者的处置话术完全不同）。</p>
 *
 * <p><b>与 Python 侧的关系</b>：{@code agent/app/core/worker_intake.py} 的 {@code _ROLES}
 * 是同一份边界文案的镜像（Agent 侧拼系统提示需要它，不能每次去调 Java）。
 * 两处必须逐字一致 —— 由 {@code scripts/e2e_p0a_worker_intake.py} 的「边界文案一致性」
 * 用例强制（对比 {@code GET /api/v1/workers} 与 {@code POST /api/v1/workers/intent}）。
 * 改了这里就要同步改 Python，否则该用例会红。</p>
 */
public enum WorkerRole {

    /** 通用办公助手：默认类型，无额外权限要求。 */
    GENERAL("通用办公助手", "通用办公问答、文案撰写与信息整理", PermissionCatalog.CHAT_BASIC,
            List.of(),
            "处理通用办公问答、文案撰写与信息整理；涉及审批权、企业数据或知识库专有内容时，需相应类型数字员工承担。"),

    /** 请假审批数字人：受理请假申请、校验证明材料、按请假制度送审与答复。 */
    LEAVE_APPROVER("请假审批数字人",
            "受理请假申请、校验请假类型与证明材料、按请假制度给出送审与答复意见",
            PermissionCatalog.APPROVAL_LEAVE,
            List.of("list_my_approvals", "list_todo_approvals"),
            "只受理请假类申请并按其制度送审；不解答与请假无关的业务问题，也不代为审批（终审权在人）。"),

    /** 知识库问答数字人：只依据企业知识库检索结果作答。 */
    KB_ASSISTANT("知识库问答数字人",
            "基于企业知识库检索企业制度与资料，据实作答并标注引用来源",
            PermissionCatalog.KB_READ,
            List.of("search_kb_documents"),
            "只依据企业知识库检索结果作答并标注来源；检索不到时明确说「知识库中没有」，不凭常识编造。"),

    /** 公文起草数字人：起草对外/对内公文。 */
    DOC_DRAFTER("公文起草数字人",
            "起草通知、请示、报告、函等公文，遵循公文格式规范",
            PermissionCatalog.DOC_DRAFT,
            // 公文起草是「纯生成」能力：不依赖任何业务工具，因此能力检查不会成为它的门槛。
            List.of(),
            "只起草通知、请示、报告、函等公文并遵循公文格式；不代签、不对外发送、不处理数据统计类需求。");

    private final String displayName;
    private final String duty;
    private final String requiredPermission;
    private final List<String> requiredTools;
    private final String boundary;

    WorkerRole(String displayName, String duty, String requiredPermission,
               List<String> requiredTools, String boundary) {
        this.displayName = displayName;
        this.duty = duty;
        this.requiredPermission = requiredPermission;
        this.requiredTools = requiredTools;
        this.boundary = boundary;
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

    /** 反向职责边界：这个类型**不做什么**。前端「能力边界卡」直接展示，不经模型改写。 */
    public String boundary() {
        return boundary;
    }

    public String requiredPermission() {
        return requiredPermission;
    }

    /** 该类型赖以工作所需的能力（工具网关注册的工具名）；空表示纯生成能力、无外部依赖。 */
    public List<String> requiredTools() {
        return requiredTools;
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
