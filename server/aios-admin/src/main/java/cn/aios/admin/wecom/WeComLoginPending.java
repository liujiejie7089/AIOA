package cn.aios.admin.wecom;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 企微登录一次性 state（V100）。start 建行（identity 为空），callback 换到身份后回填；
 * 未绑定时 H5 凭 state 引导本地登录，bind 消费后 used_at 即废。10 分钟 TTL。
 */
@Data
@TableName("wecom_login_pending")
public class WeComLoginPending {

    /** state 即主键（外部生成的一次性随机串，INPUT 型）。 */
    @TableId(value = "state", type = IdType.INPUT)
    private String state;
    private Long tenantId;
    /** callback 换到的企业微信身份；start 阶段为 null。 */
    private String wecomUserid;
    private String bizMail;
    private String name;
    private String origin;
    private String returnPath;
    private LocalDateTime createdAt;
    private LocalDateTime usedAt;
}
