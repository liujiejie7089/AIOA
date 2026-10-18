package cn.aios.org.mapper;

import cn.aios.org.entity.OrgDepartment;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** 部门 —— 机构内行政条线，树形结构，层级 ≤ 5（FR-G1） */
public interface OrgDepartmentMapper extends BaseMapper<OrgDepartment> {
}
