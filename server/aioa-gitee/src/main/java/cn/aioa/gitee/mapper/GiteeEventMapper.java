package cn.aioa.gitee.mapper;

import cn.aioa.gitee.entity.GiteeEvent;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** Gitee 操作事件日志 Mapper。 */
@Mapper
public interface GiteeEventMapper extends BaseMapper<GiteeEvent> {
}
