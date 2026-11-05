package cn.aios.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 员工打卡记录。
 *
 * <p>一天一种类型（上班 ON / 下班 OFF）只留一条：重复打卡不新增行，而是返回已有那条
 * （见 {@code AttendanceService#clock}）。这样「我今天打了几次卡」永远只有一个答案。</p>
 *
 * <p>{@code consentId} 不是装饰：它把「这条记录凭什么可以有坐标」钉到具体的授权单上，
 * 事后审计时能回答「他当时同意过吗、什么时候同意的」。管理员补录（无授权）时留 NULL。</p>
 */
@Data
@TableName("attendance_record")
public class AttendanceRecord {

    public static final String TYPE_ON = "ON";
    public static final String TYPE_OFF = "OFF";

    public static final String SOURCE_H5 = "H5";
    public static final String SOURCE_AI = "AI";
    public static final String SOURCE_ADMIN = "ADMIN";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long userId;

    /** 考勤日：按服务器时区取日期，不按客户端 —— 否则改手机时区就能跨天打卡。 */
    private LocalDate workDate;

    private String clockType;

    private LocalDateTime clockedAt;

    private BigDecimal latitude;

    private BigDecimal longitude;

    private BigDecimal accuracyM;

    private String placeName;

    private String source;

    /** 依据哪张定位授权单；NULL = 管理员补录。 */
    private Long consentId;

    private String remark;

    private LocalDateTime createdAt;

    private Long createdBy;

    private LocalDateTime updatedAt;

    private Long updatedBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
