package cn.aioa.gitee.mapper;

import cn.aioa.gitee.entity.GiteeTenantConfig;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 每租户各自的 Gitee 组织配置 Mapper。 */
@Mapper
public interface GiteeTenantConfigMapper extends BaseMapper<GiteeTenantConfig> {
}
