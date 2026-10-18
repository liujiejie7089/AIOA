package cn.aios.gitee.mapper;

import cn.aios.gitee.entity.GiteeTeam;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 部门 ↔ Gitee 团队 Mapper。 */
@Mapper
public interface GiteeTeamMapper extends BaseMapper<GiteeTeam> {
}
