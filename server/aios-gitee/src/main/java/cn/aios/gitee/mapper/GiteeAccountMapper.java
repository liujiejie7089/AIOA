package cn.aios.gitee.mapper;

import cn.aios.gitee.entity.GiteeAccount;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** Gitee 账号绑定 Mapper。 */
@Mapper
public interface GiteeAccountMapper extends BaseMapper<GiteeAccount> {
}
