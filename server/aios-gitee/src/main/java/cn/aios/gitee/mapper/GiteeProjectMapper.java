package cn.aios.gitee.mapper;

import cn.aios.gitee.entity.GiteeProject;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 平台项目 ↔ Gitee 仓库 Mapper。 */
@Mapper
public interface GiteeProjectMapper extends BaseMapper<GiteeProject> {
}
