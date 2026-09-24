package cn.aioa.resource.mapper;

import cn.aioa.resource.entity.AiExpert;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface AiExpertMapper extends BaseMapper<AiExpert> {

    /**
     * 物理删除专家行。
     *
     * <p>为什么不能用 {@code deleteById}：{@link AiExpert} 带 {@code @TableLogic}，
     * {@code deleteById} 只写 {@code deleted_at}；而 {@code ai_expert} 的唯一键是
     * {@code uk_ai_expert(tenant_id, expert_key)}，**不含** {@code deleted_at} ——
     * 软删后同一 key 再创建会直接撞唯一键（Duplicate entry），
     * 表现为「删掉的专家再也建不回来」。</p>
     *
     * <p>{@code expert_config} 的删除同样选择物理删除（见
     * {@code ExpertConfigService#deleteAll}），口径一致。</p>
     *
     * @return 实际删除行数（0 表示不存在，调用方据此判断并发删除）
     */
    @Delete("DELETE FROM ai_expert WHERE id = #{id}")
    int hardDeleteById(@Param("id") Long id);
}
