package cn.aioa.gitee.mapper;

import cn.aioa.gitee.entity.GiteePlatformConfig;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 仓库联动平台级参数 Mapper（按 provider 单行）。 */
@Mapper
public interface GiteePlatformConfigMapper extends BaseMapper<GiteePlatformConfig> {
}
