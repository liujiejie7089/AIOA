package cn.aioa.gitee.mapper;

import cn.aioa.gitee.entity.GiteeTeam;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 部门 ↔ Gitee 团队 Mapper。 */
@Mapper
public interface GiteeTeamMapper extends BaseMapper<GiteeTeam> {
}
