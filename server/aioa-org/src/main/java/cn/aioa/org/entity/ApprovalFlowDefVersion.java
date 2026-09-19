package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 审批流定义的版本快照（V60）。
 *
 * <p>每次保存定义时留一份（v1 = 新建后的状态，其后每次编辑 +1）。
 * 用途有二：一是「版本对比」（这次改了哪些节点、改前改后分别是什么），
 * 二是回溯 —— 改坏了知道上一版是什么样，而不是只能凭记忆重配一遍。</p>
 *
 * <p><b>快照而非原地覆盖</b>：只留「当前版本号」回答不了「上一版长什么样」，
 * 而管理员需要的恰恰是后者。</p>
 */
@Data
@TableName("approval_flow_def_version")
public class ApprovalFlowDefVersion {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long defId;
    private Integer version;
    private String bizType;
    private Long institutionId;
    private String name;
    /** 与 approval_flow_def.steps_json 同构：JSON 数组字符串。 */
    private String stepsJson;
    private String status;
    private String remark;
    private LocalDateTime createdAt;
    private Long createdBy;
}
