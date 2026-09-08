package cn.aioa.resource.service;

import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.AiSkill;
import cn.aioa.resource.mapper.AiExpertMapper;
import cn.aioa.resource.mapper.AiSkillMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 专家与技能目录。两者都是租户级配置（不区分用户），按 sort 升序返回。
 */
@Service
@RequiredArgsConstructor
public class CatalogService {

    private final AiExpertMapper expertMapper;
    private final AiSkillMapper skillMapper;

    public List<AiExpert> experts(Long tenantId) {
        return expertMapper.selectList(new LambdaQueryWrapper<AiExpert>()
                .eq(AiExpert::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(AiExpert::getEnabled, true)
                .orderByAsc(AiExpert::getSort));
    }

    public List<AiSkill> skills(Long tenantId) {
        return skillMapper.selectList(new LambdaQueryWrapper<AiSkill>()
                .eq(AiSkill::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(AiSkill::getEnabled, true)
                .orderByAsc(AiSkill::getSort));
    }
}
