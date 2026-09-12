package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.AgentWorker;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface AgentWorkerMapper extends BaseMapper<AgentWorker> {

    /**
     * 统计租户下数字员工条数，<b>包含已逻辑删除的行</b>。
     *
     * <p>用于「租户是否曾经被预置过」的判定：{@code BaseMapper.selectCount} 会被
     * {@code @TableLogic} 加上 {@code deleted_at IS NULL}，导致租户把预置员工全部删除后
     * 被重复预置。这里刻意绕过逻辑删除条件，保证预置动作**真正幂等**、一生只做一次。</p>
     */
    @Select("SELECT COUNT(*) FROM agent_worker WHERE tenant_id = #{tenantId}")
    long countAllByTenant(@Param("tenantId") Long tenantId);
}
