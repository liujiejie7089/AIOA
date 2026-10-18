package cn.aios.resource.mapper;

import cn.aios.resource.entity.FormSubmission;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** 表单填写数据 Mapper（唯一真源）。 */
@Mapper
public interface FormSubmissionMapper extends BaseMapper<FormSubmission> {
}
