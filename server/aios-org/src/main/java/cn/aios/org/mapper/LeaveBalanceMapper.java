package cn.aios.org.mapper;

import cn.aios.org.entity.LeaveBalance;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** 假期余额 —— 可用 = total - used - pending */
public interface LeaveBalanceMapper extends BaseMapper<LeaveBalance> {
}
