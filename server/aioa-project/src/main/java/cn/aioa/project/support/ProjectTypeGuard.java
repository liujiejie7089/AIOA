package cn.aioa.project.support;

import cn.aioa.common.exception.BizException;

/**
 * 项目类型守卫（BR-01 / BR-02 / BR-12 的**唯一判定点**）。
 *
 * <p><b>为什么必须集中在一处</b>：这三条规则分别约束「业务项目不能有仓库配置」
 * 「开发项目改回业务项目的条件」「任务仓库字段成对」—— 前端会各自隐藏、各接口会各自调用。
 * 若每个 controller/service 自己写一遍 {@code if ("BUSINESS".equals(type) && repoId != null)}
 * 之类，必然漏一处，而漏掉的那一处不报错、只是**默默写入了不该存在的仓库配置**，
 * 表现为「业务项目的详情页凭空多了个仓库」。</p>
 *
 * <p><b>前端隐藏不是安全边界</b>：前端只负责不渲染，真正的拒绝必须发生在服务端。
 * 直接构造请求（curl / 脚本）绕过界面是常规操作，守卫就是为它准备的。</p>
 */
public final class ProjectTypeGuard {

    private ProjectTypeGuard() {
    }

    /**
     * BR-01：业务项目**不接受**任何代码仓库配置。
     *
     * @param projectType          项目类型
     * @param repoConfigRequested  本次请求是否携带了仓库配置（repoId / repoIssueNo / 绑定动作）
     */
    public static void assertRepoAllowed(String projectType, boolean repoConfigRequested) {
        if (repoConfigRequested && !PmProjectType.isDev(projectType)) {
            throw BizException.badRequest("业务项目不支持代码仓库配置（当前类型：" + projectType + "）");
        }
    }

    /**
     * BR-02：项目类型创建后默认不可改；仅当「未绑定任何仓库 **且** 无任务带仓库信息」时允许 {@code DEV → BUSINESS}。
     *
     * <p>反方向（{@code BUSINESS → DEV}）**始终允许**：业务项目没有任何仓库信息需要迁移，
     * 把它升级为开发项目只是打开了仓库配置面，不会造成数据不一致。
     * 而 {@code DEV → BUSINESS} 若已有仓库/任务关联，改完会留下「业务项目却有仓库绑定的孤儿行」——
     * 所以必须拒绝，并把冲突计数写进错误信息（用户据此知道该先解绑什么，而不是只看到「不允许」）。</p>
     */
    public static void assertTypeChangeable(String fromType, String toType,
                                            long boundRepoCount, long tasksWithRepoCount) {
        if (fromType == null || toType == null || fromType.equals(toType)) {
            return;
        }
        if (!PmProjectType.isValid(toType)) {
            throw BizException.badRequest("未知项目类型：" + toType);
        }
        if (PmProjectType.BUSINESS.equals(toType)) {
            if (boundRepoCount > 0 || tasksWithRepoCount > 0) {
                throw new BizException(409, "已存在仓库关联（已绑仓库 " + boundRepoCount
                        + " 个、带仓库信息的任务 " + tasksWithRepoCount + " 条），不能改为业务项目；"
                        + "请先解绑仓库并移除任务的仓库信息");
            }
        }
    }

    /**
     * BR-12：任务的仓库字段成对约束 —— {@code repoId} 与 {@code repoIssueNo} 要么都空、要么都有。
     *
     * <p>只有 repoId 而无 issue 号，会把界面带向「跳到一个不存在的 issue」；
     * 只有 issue 号而无 repoId，则不知道该去哪个仓库找它。二者必须成对。</p>
     *
     * <p>单独填 {@code repoBranch} / {@code repoCommitSha} 但不填 {@code repoId} 同样被拒 ——
     * 分支/提交都是「仓库内的概念」，没有仓库就没有意义。</p>
     */
    public static void assertRepoPairing(Long repoId, String repoIssueNo,
                                         String repoBranch, String repoCommitSha) {
        boolean hasIssue = repoIssueNo != null && !repoIssueNo.isBlank();
        boolean hasBranch = repoBranch != null && !repoBranch.isBlank();
        boolean hasCommit = repoCommitSha != null && !repoCommitSha.isBlank();
        boolean hasAnyRepoDetail = hasIssue || hasBranch || hasCommit;

        if (repoId == null && hasAnyRepoDetail) {
            throw BizException.badRequest("填写 issue / 分支 / 提交前必须先选择代码仓库");
        }
        if (repoId != null && !hasIssue) {
            throw BizException.badRequest("选择代码仓库后必须填写关联的 issue 号");
        }
    }

    /** 任务是否携带任何仓库信息（BR-01 在任务写入路径上的入口判据）。 */
    public static boolean taskHasRepoConfig(Long repoId, String repoIssueNo,
                                            String repoBranch, String repoCommitSha) {
        return repoId != null
                || (repoIssueNo != null && !repoIssueNo.isBlank())
                || (repoBranch != null && !repoBranch.isBlank())
                || (repoCommitSha != null && !repoCommitSha.isBlank());
    }
}
