package cn.aioa.org.mapper;

import cn.aioa.org.entity.LeaveBalance;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** 假期余额 —— 可用 = total - used - pending */
public interface LeaveBalanceMapper extends BaseMapper<LeaveBalance> {
}
