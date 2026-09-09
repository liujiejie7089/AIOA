package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 经营数据看板 —— 指标卡（V1.2 新增）。
 * period：month=本月 / quarter=本季；up=1 上涨、0 下降（前端据此决定涨跌标记方向）。
 * 数据由管理端维护，用户端只读。
 */
@Data
@TableName("biz_kpi")
public class BizKpi {

    public static final String PERIOD_MONTH = "month";
    public static final String PERIOD_QUARTER = "quarter";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String period;

    private String label;

    private String valueText;

    private String deltaText;

    /** 1=上涨 0=下降 */
    private Integer up;

    private String compareLabel;

    private Integer sortNo;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
