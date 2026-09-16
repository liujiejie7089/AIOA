package cn.aioa.gitee.service;

import cn.aioa.gitee.client.GiteeApiException;
import cn.aioa.gitee.entity.GiteeProject;
import cn.aioa.gitee.entity.GiteeTask;
import cn.aioa.gitee.mapper.GiteeProjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * 项目级全量校准任务处理器（{@code SYNC_ALL}）。
 *
 * <p><b>为什么要单独一个任务类型</b>：成员校准需要**读 Gitee 协作者列表**（一次出网调用），
 * 而 {@code SYNC_MEMBER} 是「按成员推一次写操作」。把「读远端做对账」塞进定时器线程
 * 会让调度线程被网络 IO 阻塞；入队后由队列消费，天然受 batch 与限流保护。</p>
 *
 * <p>不存在「实体被删」的失败判定：项目在排队期间被删时直接跳过而不是报错 ——
 * 校准是**收敛性**动作，业务对象都没了就没有需要收敛的东西。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class GiteeCalibrateTaskHandler implements GiteeTaskHandler {

    private final GiteeProjectMapper projectMapper;
    private final GiteeMemberService memberService;

    @Override
    public List<String> types() {
        return List.of(GiteeTask.TYPE_SYNC_ALL);
    }

    @Override
    public void handle(GiteeTask task) {
        Long projectId = task.getBizId();
        if (projectId == null) {
            throw new GiteeApiException(0, "校准任务缺少项目 id", false);
        }
        GiteeProject p = projectMapper.selectById(projectId);
        if (p == null || !StringUtils.hasText(p.getGiteeRepo())) {
            log.info("Gitee 校准：项目不存在或仓库未就绪，任务跳过 project={}", projectId);
            return;
        }
        memberService.calibrate(p);
    }
}
