package cn.aios.resource.mapper;

import cn.aios.resource.entity.FormTemplateVersion;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/** 表单定义版本快照 Mapper。 */
@Mapper
public interface FormTemplateVersionMapper extends BaseMapper<FormTemplateVersion> {

    /**
     * 取某模板当前最大版本号（不含逻辑删除行）。
     *
     * <p>用于「更新自动升版」前确认基准版本；返回 0 表示该模板尚无任何快照。</p>
     */
    @Select("SELECT COALESCE(MAX(version), 0) FROM form_template_version WHERE template_id = #{templateId}")
    int selectMaxVersion(@Param("templateId") Long templateId);
}
