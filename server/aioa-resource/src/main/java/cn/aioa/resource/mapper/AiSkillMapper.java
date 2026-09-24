package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.AiSkill;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface AiSkillMapper extends BaseMapper<AiSkill> {

    /**
     * 物理删除某租户下挂靠某专家的全部技能（删除专家时级联）。
     *
     * <p>为什么是物理删除：{@code ai_skill} 的唯一键是
     * {@code uk_ai_skill(tenant_id, skill_name)}，**不含** {@code deleted_at} ——
     * 软删会让同名技能再也建不回来（与 {@code ai_expert} 同一个坑）。</p>
     *
     * @return 实际删除行数
     */
    @Delete("DELETE FROM ai_skill WHERE tenant_id = #{tenantId} AND expert_key = #{expertKey}")
    int hardDeleteByExpert(@Param("tenantId") Long tenantId, @Param("expertKey") String expertKey);
}
