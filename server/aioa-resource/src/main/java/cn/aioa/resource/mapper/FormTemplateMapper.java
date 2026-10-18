package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.FormTemplate;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 表单定义 Mapper（照 AgentWorkerMapper 风格）。 */
@Mapper
public interface FormTemplateMapper extends BaseMapper<FormTemplate> {
}
