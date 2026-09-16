package cn.aioa.org.mapper;

import cn.aioa.org.entity.OrgDuty;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 职务字典 Mapper（对标 O2OA 的 Duty）。 */
@Mapper
public interface OrgDutyMapper extends BaseMapper<OrgDuty> {
}
