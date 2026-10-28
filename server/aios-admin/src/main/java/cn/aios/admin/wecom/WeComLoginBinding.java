package cn.aios.admin.wecom;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 企业微信 userid ↔ 本地账号绑定（V100）。命中即静默登录，见 WeComLoginService。
 */
@Data
@TableName("wecom_login_binding")
public class WeComLoginBinding {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String wecomUserid;
    private String bizMail;
    private String name;
    private Long userId;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
