package cn.aioa.project.mapper;

import cn.aioa.project.entity.PmTask;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 项目任务 Mapper（业务任务，非 gitee_task 异步队列）。 */
@Mapper
public interface PmTaskMapper extends BaseMapper<PmTask> {
}
