package cn.aioa.gitee.mapper;

import cn.aioa.gitee.entity.GiteeTask;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;

/** Gitee 异步任务队列 Mapper。 */
@Mapper
public interface GiteeTaskMapper extends BaseMapper<GiteeTask> {

    /**
     * 原子领取一个任务（抢占式）。
     *
     * <p>返回 1 表示领取成功。<b>不能用「先 select 再 update」</b>：两个工作线程会同时
     * 读到同一条 PENDING 任务，然后一起执行 —— 表现是「同一仓库被重复创建 / 同一事件被处理两次」。
     * 把状态判断写进 UPDATE 的 WHERE 里，由数据库保证只有一个线程能改成功。</p>
     */
    @Update("""
            UPDATE gitee_task
               SET status = 'RUNNING', locked_at = #{now}, locked_by = #{worker}, updated_at = #{now}
             WHERE id = #{id} AND status = 'PENDING'
            """)
    int claim(@Param("id") Long id, @Param("worker") String worker, @Param("now") LocalDateTime now);
}
