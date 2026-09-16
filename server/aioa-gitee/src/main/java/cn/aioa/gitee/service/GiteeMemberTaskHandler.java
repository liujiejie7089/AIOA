package cn.aioa.gitee.service;

import cn.aioa.gitee.client.GiteeApiException;
import cn.aioa.gitee.client.GiteeClient;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.entity.GiteeRepoMember;
import cn.aioa.gitee.entity.GiteeTask;
import cn.aioa.gitee.mapper.GiteeProjectMapper;
import cn.aioa.gitee.mapper.GiteeRepoMemberMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 仓库成员权限同步任务处理器。
 *
 * <p>把平台侧的「项目成员 + 角色」落到 Gitee 的**仓库协作者**上 ——
 * 这是部门隔离的最后一道：仓库即便公开在组织下，跨部门成员在 Gitee 侧也拿不到写权限。</p>
 *
 * <p><b>已存在即成功</b>：Gitee 对已在协作者列表中的用户可能返回 422/400。
 * 若把它当失败，任务会无意义地重试到上限。因此「已在协作者中」被显式识别为成功
 * （幂等语义：目标是「这个人是协作者」，而不是「这次调用必须新建关系」）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class GiteeMemberTaskHandler implements GiteeTaskHandler {

    public static final String OP_ADD = "ADD";
    public static final String OP_REMOVE = "REMOVE";
    public static final String OP_CALIBRATE = "CALIBRATE";

    private final GiteeProjectMapper projectMapper;
    private final GiteeRepoMemberMapper memberMapper;
    private final GiteeClient client;
    private final GiteeTokenService tokenService;
    private final GiteeTaskService taskService;

    @Override
    public List<String> types() {
        return List.of(GiteeTask.TYPE_SYNC_MEMBER);
    }

    @Override
    public void handle(GiteeTask task) {
        Map<String, Object> payload = taskService.payloadOf(task);
        String op = String.valueOf(payload.getOrDefault("op", OP_ADD));
        Long memberId = task.getBizId();

        GiteeRepoMember member = memberId == null ? null : memberMapper.selectById(memberId);
        if (member == null) {
            // 成员已被移除 → 任务作废（不视为失败）
            log.info("Gitee 成员同步：成员记录已不存在，任务跳过 id={}", memberId);
            return;
        }
        GiteeProject project = projectMapper.selectById(member.getProjectId());
        if (project == null || !StringUtils.hasText(project.getGiteeRepo())) {
            throw new GiteeApiException(0, "项目或仓库信息不完整，无法同步成员权限", true);
        }
        if (!StringUtils.hasText(member.getGiteeUsername())) {
            if (OP_REMOVE.equals(op)) {
                // 未绑定 Gitee 的成员，远端本来就没有他的协作者关系 → 本地直接收尾，
                // 不能打回 PENDING：那会让「移除成员」永远显示为「待处理」。
                softDeleteMember(member);
                return;
            }
            // 该成员还没绑定 Gitee：不能同步，但不是错误 —— 标记 PENDING 等其绑定后再校准
            memberMapper.updateById(pendingMember(member, "成员尚未绑定 Gitee 账号，待绑定后由定时校准补齐"));
            return;
        }

        String token = tokenService.requireAccessTokenForProject(project);
        try {
            if (OP_REMOVE.equals(op)) {
                client.removeCollaborator(token, project.getGiteeOwner(), project.getGiteeRepo(),
                        member.getGiteeUsername());
                softDeleteMember(member);
            } else {
                client.addCollaborator(token, project.getGiteeOwner(), project.getGiteeRepo(),
                        member.getGiteeUsername(), toGiteePermission(member.getRole()));
                memberMapper.updateById(syncedMember(member));
            }
        } catch (GiteeApiException e) {
            if (isAlreadyCollaborator(e) || (OP_REMOVE.equals(op) && e.getStatus() == 404)) {
                // 目标状态已达成 → 幂等成功
                if (OP_REMOVE.equals(op)) {
                    softDeleteMember(member);
                } else {
                    memberMapper.updateById(syncedMember(member));
                }
                return;
            }
            memberMapper.updateById(failedMember(member, e.getMessage()));
            throw e;
        }
    }

    /**
     * 收尾「成员已移除」。
     *
     * <p><b>必须用 {@code deleteById} 而不是把 {@code deletedAt} 塞进 {@code updateById}</b>：
     * MyBatis-Plus 在 updateById 生成的 SET 子句里会**排除逻辑删除字段**（它由
     * {@code deleteById} 专管），所以「setDeletedAt + updateById」看起来执行成功、
     * 实际什么都不改 —— 表现就是 Gitee 侧协作者已回收，平台成员列表里那一条却一直在
     * （实测踩过）。</p>
     */
    private void softDeleteMember(GiteeRepoMember m) {
        memberMapper.updateById(syncedMember(m));
        memberMapper.deleteById(m.getId());
    }

    /** 平台角色 → Gitee 协作者权限。 */
    static String toGiteePermission(String role) {
        if (role == null) {
            return "write";
        }
        return switch (role.toUpperCase(Locale.ROOT)) {
            case GiteeRepoMember.ROLE_ADMIN -> "admin";
            case GiteeRepoMember.ROLE_READ -> "read";
            default -> "write";
        };
    }

    private static boolean isAlreadyCollaborator(GiteeApiException e) {
        String m = e.getMessage() == null ? "" : e.getMessage().toLowerCase(Locale.ROOT);
        return e.getStatus() == 422 || m.contains("already") || m.contains("已存在")
                || m.contains("has been added") || m.contains("repeated");
    }

    private static GiteeRepoMember syncedMember(GiteeRepoMember m) {
        GiteeRepoMember upd = new GiteeRepoMember();
        upd.setId(m.getId());
        upd.setSyncStatus(GiteeRepoMember.SYNC_SYNCED);
        upd.setLastError(null);
        upd.setSyncedAt(LocalDateTime.now());
        upd.setUpdatedAt(LocalDateTime.now());
        return upd;
    }

    private static GiteeRepoMember pendingMember(GiteeRepoMember m, String reason) {
        GiteeRepoMember upd = new GiteeRepoMember();
        upd.setId(m.getId());
        upd.setSyncStatus(GiteeRepoMember.SYNC_PENDING);
        upd.setLastError(reason);
        upd.setUpdatedAt(LocalDateTime.now());
        return upd;
    }

    private static GiteeRepoMember failedMember(GiteeRepoMember m, String error) {
        GiteeRepoMember upd = new GiteeRepoMember();
        upd.setId(m.getId());
        upd.setSyncStatus(GiteeRepoMember.SYNC_FAILED);
        upd.setLastError(error == null ? "未知错误" : (error.length() > 250 ? error.substring(0, 250) : error));
        upd.setUpdatedAt(LocalDateTime.now());
        return upd;
    }
}
