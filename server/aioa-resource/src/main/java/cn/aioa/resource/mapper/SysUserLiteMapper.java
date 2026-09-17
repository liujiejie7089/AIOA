package cn.aioa.resource.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Map;

/**
 * 资源域只读查询 sys_user 的轻量视图（仅取分发所需字段，避免引入 aioa-admin 依赖）。
 */
@Mapper
public interface SysUserLiteMapper {

    /** 取用户邮箱（EMAIL 通道收件地址解析用）。 */
    @Select("SELECT id, email FROM sys_user WHERE deleted_at IS NULL AND id = #{id} LIMIT 1")
    Map<String, Object> selectLite(@Param("id") Long id);
}
