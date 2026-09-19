package cn.aioa.org.mapper;

import cn.aioa.org.entity.ApprovalFlowDefVersion;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ApprovalFlowDefVersionMapper extends BaseMapper<ApprovalFlowDefVersion> {

    /** 当前最大版本号；无快照时返回 null（调用方按 0 处理）。 */
    @Select("SELECT MAX(version) FROM approval_flow_def_version WHERE def_id = #{defId}")
    Integer selectMaxVersion(@Param("defId") Long defId);
}
