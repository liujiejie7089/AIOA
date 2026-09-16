package cn.aioa.gitee.mapper;

import cn.aioa.gitee.entity.GiteeOauthState;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** OAuth2 state Mapper。 */
@Mapper
public interface GiteeOauthStateMapper extends BaseMapper<GiteeOauthState> {
}
