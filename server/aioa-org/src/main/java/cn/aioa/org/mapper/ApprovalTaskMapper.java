package cn.aioa.org.mapper;

import cn.aioa.org.entity.ApprovalTask;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** 审批任务 —— 多级流转节点（与 approval_order 并行） */
public interface ApprovalTaskMapper extends BaseMapper<ApprovalTask> {
}
