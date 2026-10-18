package cn.aios.gitee.mapper;

import cn.aios.gitee.entity.GiteeRepoMember;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** Gitee 仓库成员 Mapper。 */
@Mapper
public interface GiteeRepoMemberMapper extends BaseMapper<GiteeRepoMember> {
}
