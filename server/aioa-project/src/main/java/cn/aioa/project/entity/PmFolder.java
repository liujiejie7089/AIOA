package cn.aioa.project.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 文档文件夹（企业级公共 / 项目专属两类同表）。表 {@code pm_folder}（V72）。
 *
 * <p>设计依据 {@code docs/40 §6.2} + {@code docs/43}。</p>
 *
 * <p><b>两类为什么同表</b>：结构完全一致（父子树 + 命名唯一），只差 {@link #scope} 与是否带
 * {@link #projectId}；拆两表会让 BR-07 的级联策略写两遍、进项目文档页要同时查两棵树。</p>
 *
 * <p><b>{@link #parentId} 与 {@link #projectId} 用 {@code 0} 而非 NULL 表示「根 / 企业级」</b>：
 * MySQL 唯一键里 NULL 视为彼此不同 ⇒ 若用 NULL，同一根下可插两条同名文件夹，唯一约束形同虚设
 * （见 V72 文件头修正说明）。上层一律用 0，不出现 NULL。</p>
 *
 * <p>生成列 {@code alive} 不映射（V24 约定）。</p>
 */
@Data
@TableName("pm_folder")
public class PmFolder {

    /** scope：企业级公共（跨项目，projectId=0）。 */
    public static final String SCOPE_ENTERPRISE = "ENTERPRISE";
    /** scope：项目专属（挂在 projectId 下）。 */
    public static final String SCOPE_PROJECT = "PROJECT";

    /** 根文件夹的 parentId 取值（不用 NULL，见类注释）。 */
    public static final long ROOT_PARENT = 0L;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** ENTERPRISE / PROJECT，见本类常量。 */
    private String scope;

    /** scope=PROJECT 时为真实项目 id；ENTERPRISE 固定 0。 */
    private Long projectId;

    /** 父文件夹 id；0=根。 */
    private Long parentId;

    private String name;

    /** 物化路径 {@code /1/12/}，便于子树查询与防环。 */
    private String path;

    /** LOCAL 落 sys_file / CLOUD 云盘（抽象位，docs/40 §8.3）。 */
    private String storageKind;

    /** 云盘侧文件夹 id/path（storageKind=CLOUD 时）。 */
    private String cloudRef;

    private Long createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
