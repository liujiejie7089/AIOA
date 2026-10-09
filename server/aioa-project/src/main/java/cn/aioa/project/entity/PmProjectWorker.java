package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 项目 ↔ 数字员工 分配。表 {@code pm_project_worker}（V74）。设计依据 {@code docs/43 §5}。
 *
 * <p>用户关键词「分配项目数字人」= 把**已存在**的数字员工（{@code agent_worker}）挂到项目上，
 * 一个项目可挂多个、一个数字员工可服务多个项目（M:N，见 docs/43 A5）。
 * <b>绝不新建第二套数字人</b>——否则两套账号 / 两套职责，与「权限码单入口」纪律冲突
 * （同 {@code docs/40} ADR-007 的取舍）。</p>
 *
 * <p>生成列 {@code alive} 不映射（V24 约定）。</p>
 */
@Data
@TableName("pm_project_worker")
public class PmProjectWorker {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long projectId;

    /** {@code agent_worker.id}（既有数字员工，非新建）。 */
    private Long workerId;

    /** 在本项目的用途说明（如「项目助理」「合同初审」）。 */
    private String assignRole;

    /** 0=已停用（停用后本项目不再下发其上下文）。 */
    private Integer enabled;

    /** 分配人 {@code sys_user.id}。 */
    private Long assignedBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
