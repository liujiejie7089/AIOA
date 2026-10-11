package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.SysOrgConfig;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 机构作用域系统参数覆盖值 Mapper（V80，docs/44 §2.5 B 案）。
 */
@Mapper
public interface SysOrgConfigMapper extends BaseMapper<SysOrgConfig> {
}
