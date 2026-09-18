package cn.aioa.gitee.service;

import cn.aioa.gitee.client.RepoProviderException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「已经是协作者」的判定必须锚定文案，不能只看状态码。
 *
 * <p>守的是最危险的一类缺陷（假阴/假绿）：把「没加上」判成「已加上」，
 * 管理端显示绿色「已同步」，而成员对仓库其实没有任何权限。</p>
 *
 * <p>真机实测（Gitea 1.26.2，2026-09-18）：</p>
 * <pre>
 * PUT /api/v1/repos/AI-OA/AIOA_FrontWeb/collaborators/no-such-gitea-user-xyz
 *   → 422 {"message":"user does not exist [uid: 0, name: no-such-gitea-user-xyz]"}
 * PUT /api/v1/repos/AI-OA/AIOA_FrontWeb/collaborators/liujiejie   （已存在）
 *   → 204（幂等成功，不走异常分支）
 * </pre>
 */
class GiteeMemberAlreadyCollaboratorTest {

    @Test
    @DisplayName("Gitea 实测：422「user does not exist」绝不能判成已达成（否则成员假绿）")
    void giteaUnknownUser422IsNotSuccess() {
        RepoProviderException e = RepoProviderException.of(422,
                "user does not exist [uid: 0, name: no-such-gitea-user-xyz]");
        assertFalse(GiteeMemberTaskHandler.isAlreadyCollaborator(e),
                "用户不存在 ≠ 已是协作者；判成成功会让没有权限的成员显示 SYNCED");
    }

    @Test
    @DisplayName("422 文案里明确说「已是协作者」才判成功")
    void explicitAlreadyOn422IsSuccess() {
        for (String msg : new String[]{
                "user is already a collaborator",
                "该用户已在协作者中",
                "repeated collaborator",
                "该协作者已存在"}) {
            assertTrue(GiteeMemberTaskHandler.isAlreadyCollaborator(RepoProviderException.of(422, msg)), msg);
        }
    }

    @Test
    @DisplayName("400/409 上的「已存在/重复」同样判成功（不同托管方措辞不同）")
    void alreadyOnOther4xxIsSuccess() {
        assertTrue(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(400, "collaborator has been added")));
        assertTrue(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(409, "repeated")));
    }

    @Test
    @DisplayName("状态码不是 4xx 的一律不判成功（5xx 上的偶然同词不构成「已达达成」）")
    void non4xxNeverTreatedAsDone() {
        assertFalse(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(500, "already broken upstream")));
        assertFalse(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(0, "already connecting")));
    }

    @Test
    @DisplayName("无关的 4xx 一律判失败（404 仓库不存在、403 无权限）")
    void unrelatedFailuresStayFailures() {
        assertFalse(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(404, "Not Found")));
        assertFalse(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(403, "forbidden")));
        assertFalse(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(401, "Unauthorized")));
    }

    @Test
    @DisplayName("文案为空时不判成功（不能靠状态码独自放行）")
    void nullMessageIsNotSuccess() {
        assertFalse(GiteeMemberTaskHandler.isAlreadyCollaborator(
                RepoProviderException.of(422, null)));
    }
}
