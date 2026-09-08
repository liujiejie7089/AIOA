package cn.aioa.resource.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/** 词元包商品（FR-G4 商品列表）。 */
@Data
@TableName("quota_package")
public class QuotaPackage {

    public static final String STATUS_ONSALE = "ONSALE";

    @TableId(type = IdType.AUTO)
    private Long id;
    private String packageCode;
    private String packageName;
    private Long tokens;
    /** 价格（分），避免浮点误差 */
    private Integer priceCents;
    private String status;
    private Integer sort;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
}
