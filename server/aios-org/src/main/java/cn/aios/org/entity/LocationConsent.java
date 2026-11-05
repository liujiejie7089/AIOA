package cn.aios.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 设备定位调用申请（一次性凭据）。
 *
 * <p>语义：系统（或数字人）向用户申请「用一次手机定位」，<b>用户明确同意后</b>才允许把坐标
 * 写进 {@link AttendanceRecord}。没有 GRANTED 的授权单，打卡接口一律拒绝 —— 这是「必须用户同意」
 * 在服务端的落地方式，不依赖前端自觉。</p>
 *
 * <p>为什么不复用 {@code sys_config} 之类的地方放一个开关：授权是**每用户、每次、有有效期**的，
 * 一个全局开关只能表达「允不允许」，表达不了「这一次、只用于打卡、5 分钟内有效」。</p>
 */
@Data
@TableName("location_consent")
public class LocationConsent {

    /** 等用户决定。 */
    public static final String STATUS_PENDING = "PENDING";
    /** 用户已同意（此时才有坐标）。 */
    public static final String STATUS_GRANTED = "GRANTED";
    /** 已被一次打卡消费掉；同一张单不能打第二次。 */
    public static final String STATUS_USED = "USED";
    /** 用户点了「不允许」。 */
    public static final String STATUS_DENIED = "DENIED";
    /** 超过 expiresAt 仍未被使用（读时判定并回写，没有定时任务）。 */
    public static final String STATUS_EXPIRED = "EXPIRED";

    public static final String PURPOSE_ATTENDANCE = "ATTENDANCE";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 被申请定位的人 = 打卡人，只能是本人。 */
    private Long userId;

    /** 一次性凭据：打卡接口必须原样回传，服务端据此证明「这一张就是用户点过的那一张」。 */
    private String token;

    private String purpose;

    /** 给用户看的申请文案（谁申请、做什么、有效期多久）。 */
    private String prompt;

    private String status;

    /** 发起方：H5（用户点入口）/ AI（数字人调用工具）。用于区分「谁问的」。 */
    private String origin;

    private BigDecimal latitude;

    private BigDecimal longitude;

    /** 浏览器上报的定位精度（米）。 */
    private BigDecimal accuracyM;

    /** 用户同意时界面上那句话的原文留痕。 */
    private String consentText;

    private LocalDateTime grantedAt;

    private LocalDateTime deniedAt;

    private LocalDateTime usedAt;

    /** 过期时间：服务端按自己的时钟判定，不信任前端时间。 */
    private LocalDateTime expiresAt;

    private LocalDateTime createdAt;

    private Long createdBy;

    private LocalDateTime updatedAt;

    private Long updatedBy;

    @TableLogic
    private LocalDateTime deletedAt;

    /** 是否还可用于打卡（状态 + 时效一起看，避免调用方各自判断漏掉一个条件）。 */
    public boolean usable(LocalDateTime now) {
        return STATUS_GRANTED.equals(status) && expiresAt != null && expiresAt.isAfter(now);
    }
}
