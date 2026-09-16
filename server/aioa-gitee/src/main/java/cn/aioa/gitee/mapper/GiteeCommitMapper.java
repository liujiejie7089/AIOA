package cn.aioa.gitee.mapper;

import cn.aioa.gitee.entity.GiteeCommit;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** Gitee 提交记录 Mapper。 */
@Mapper
public interface GiteeCommitMapper extends BaseMapper<GiteeCommit> {
}
