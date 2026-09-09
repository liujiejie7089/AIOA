package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.ApprovalOrder;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ApprovalOrderMapper extends BaseMapper<ApprovalOrder> {

    /** 查用户显示名（昵称优先）：JWT 不携带昵称时，提交审批快照发起人姓名用。 */
    @Select("SELECT COALESCE(nickname, username, CONCAT('用户#', #{userId})) FROM sys_user "
            + "WHERE id = #{userId} AND deleted_at IS NULL LIMIT 1")
    String selectDisplayName(@Param("userId") Long userId);
}
