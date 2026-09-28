package cn.aioa.org.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
/**
 * 资源按机构授权 —— 专家/技能/模型/KB/数字员工（FR-E1/E2）
 *
 * 表：resource_grant（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("resource_grant")
public class ResourceGrant {
    public static final String TYPE_EXPERT = "EXPERT";
    public static final String TYPE_SKILL = "SKILL";
    public static final String TYPE_MODEL = "MODEL";
    public static final String TYPE_KB = "KB";
    public static final String TYPE_WORKER = "WORKER";

    /**
     * 可授权资源类型的**唯一权威清单**。
     *
     * <p>此前 `EXPERT/SKILL/MODEL/KB` 这份列表在 {@code ResourceGrantService} 里被抄了三份
     * （授权目录的 resTypes、grant() 的白名单、成员端 byType 的预置），而管理端下拉早已提供
     * 「数字员工」选项 —— 三处都漏了 WORKER，于是<b>选了数字员工点保存必被
     * 「不支持的资源类型：WORKER」拒绝</b>，数字员工事实上永远授权不了。</p>
     *
     * <p>新增类型只改这里一处：目录、白名单、成员端分组同时生效（铁律 #4：常量只有一个入口）。</p>
     */
    public static final List<String> ALL_TYPES =
            List.of(TYPE_EXPERT, TYPE_SKILL, TYPE_MODEL, TYPE_KB, TYPE_WORKER);

    /** 类型码 → 中文名。目录接口用它下发，前端不得再复刻一份。 */
    public static final Map<String, String> TYPE_NAMES = Map.of(
            TYPE_EXPERT, "专家",
            TYPE_SKILL, "技能",
            TYPE_MODEL, "模型",
            TYPE_KB, "知识库",
            TYPE_WORKER, "数字员工");


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private Long institutionId;

    private String resType;

    private Long resId;

    private String resKey;

    private String resName;

    private String extra;

    private Boolean enabled;

    private Long grantedBy;

    private LocalDateTime grantedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    // 注意：resource_grant 表**无** created_by 列（授权人由 granted_by 承载），此处不得映射，否则查询报 Unknown column。

    @TableLogic
    private LocalDateTime deletedAt;
}
