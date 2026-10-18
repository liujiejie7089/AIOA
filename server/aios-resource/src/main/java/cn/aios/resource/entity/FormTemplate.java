package cn.aios.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 表单定义（docs/52 P1/P4）。
 *
 * <p>一份 JSON Schema（Draft 2020-12）承载「渲染 / 校验 / LLM 参数」三处同源；
 * {@code schema_json}/{@code layout_json}/{@code receipt_json} 用 {@code String} 存，
 * 序列化/反序列化在服务层用 Jackson 显式做（不引入 MyBatis typeHandler，便于校验与报错）。</p>
 *
 * <p>版本：每次更新 {@code version + 1}，并把旧版本写入 {@code form_template_version} 快照，永不覆盖。</p>
 */
@Data
@TableName("form_template")
public class FormTemplate {

    /** 生效态：启用。 */
    public static final String STATUS_ACTIVE = "ACTIVE";
    /** 生效态：停用。 */
    public static final String STATUS_DISABLED = "DISABLED";

    /** 分流策略：台账（仅落库即完成）。 */
    public static final String POLICY_LEDGER = "LEDGER";
    /** 分流策略：审批（走 ApprovalFlowService）。 */
    public static final String POLICY_APPROVAL = "APPROVAL";
    /** 分流策略：回填对话（仅标记，由调用方续跑）。 */
    public static final String POLICY_RESUME = "RESUME";

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 租户；0 = 平台默认模板（租户无定义时回退）。 */
    private Long tenantId;

    /** 机构（可空=租户级）。 */
    private Long institutionId;

    /** 表单码，数字人与工具用它引用，如 leave_request。租户内唯一。 */
    private String code;

    /** 中文名。 */
    private String name;

    /** 归属功能模块稳定码，如 leave / expense。 */
    private String moduleCode;

    /** 提交后进审批的 bizType；空=不走审批。 */
    private String bizType;

    /** JSON Schema（渲染/校验/LLM 参数三处同源）。 */
    private String schemaJson;

    /** 分组/栅格/顺序；空=按 schema 顺序。 */
    private String layoutJson;

    /** 分流策略：LEDGER / APPROVAL / RESUME，可组合如 APPROVAL+RESUME。 */
    private String submitPolicy;

    /** 声明式回执（标题模板/展示字段/按钮组）。 */
    private String receiptJson;

    /** 当前生效版本号，每次更新 +1。 */
    private Integer version;

    /** ACTIVE / DISABLED。 */
    private String status;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    /** 软删时间；配合生成列 alive 保证「活行唯一」。 */
    @TableLogic
    private LocalDateTime deletedAt;
}
