package cn.aioa.org.mapper;

import cn.aioa.org.entity.QuotaAllocLog;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** 配额分配流水 —— 贯穿四级链路，审计依据 */
public interface QuotaAllocLogMapper extends BaseMapper<QuotaAllocLog> {
}
