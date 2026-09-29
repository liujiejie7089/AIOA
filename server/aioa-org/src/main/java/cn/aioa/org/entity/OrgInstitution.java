package cn.aioa.org.entity;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.org.InstitutionStatus;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
/**
 * 机构（企业）—— 租户内具有法人资格的组织实体（FR-B）
 *
 * 表：org_institution（V24 企业入驻迁移）
 * 注：表中 `alive` 为生成列（IF(deleted_at IS NULL,1,NULL)，配合唯一键防重），**不映射**。
 */
@Data
@TableName("org_institution")
public class OrgInstitution {
    /**
     * 状态取值。**唯一权威在** {@link InstitutionStatus}（aioa-common）——
     * 因为 aioa-admin 的人员管理要用原生 SQL 读这张表，同一条规则必须两边同源。
     * 这里只做别名，不要再写第二份字面量。
     */
    public static final String STATUS_ACTIVE = InstitutionStatus.ACTIVE;
    public static final String STATUS_SUSPENDED = InstitutionStatus.SUSPENDED;
    public static final String STATUS_CLOSED = InstitutionStatus.CLOSED;

    /**
     * 把「已注销机构退出运营面」这一条规则**只写一次**（MyBatis-Plus 版本）。
     *
     * <p>等价于 {@link InstitutionStatus#sqlOperational(String)}：{@code status IS NULL OR status <> 'CLOSED'}。
     * 不能用裸的 {@code .ne(status, 'CLOSED')} —— SQL 三值逻辑下它会连 {@code NULL} 行一起排除，
     * 把状态漏写的历史行静默藏掉（宁可多展示，不可静默少展示）。</p>
     *
     * <p>使用点：机构清单 / 入驻总览 / 资源授权 / 费用分摊 / 配额等一切「运营面」查询。
     * 需要看档案（含已注销）的调用方必须显式声明（{@code includeClosed=true}），不要在本方法上开口子。</p>
     */
    public static void excludeClosed(LambdaQueryWrapper<OrgInstitution> w) {
        w.and(x -> x.isNull(OrgInstitution::getStatus)
                .or().ne(OrgInstitution::getStatus, STATUS_CLOSED));
    }

    /** 该机构是否参与运营面（与 {@link #excludeClosed} 同一判定的对象版）。 */
    public boolean operational() {
        return InstitutionStatus.operational(status);
    }

    /**
     * 机构类型（{@code org_type}）—— **唯一权威清单**。
     *
     * <p>规格（用户原话）分五类：政府 / 企业 / 事业单位 / 社会组织 / 其他。
     * 展示名见 {@link #TYPES}。</p>
     *
     * <p><b>为什么清单必须只有这一处</b>：此前前端 `InstitutionView.vue` 自己写了第二套枚举
     * （`GOVERNMENT / INSTITUTION / STATE_OWNED / PRIVATE / ASSOCIATION`），与本类不一致 ⇒
     * 库里最多的 {@code ENTERPRISE} 在管理端下拉里**根本选不到**（编辑既有企业机构时下拉显示裸码），
     * 而用户选「国有企业/民营企业」写库的 {@code STATE_OWNED}/{@code PRIVATE} 后端不认识、列表标签也标不出来。
     * 这就是本项目反复出现的「同一判定点两处实现」（铁律 #1）。现在下拉的选项与列表的标签都由
     * {@code GET /api/v1/tenant/institution-types} 下发（见 {@code InstitutionService#typeOptions()}），
     * 前端不得再自建一份。</p>
     */
    public static final String TYPE_GOVERNMENT = "GOVERNMENT";
    public static final String TYPE_ENTERPRISE = "ENTERPRISE";
    public static final String TYPE_INSTITUTION = "INSTITUTION";
    public static final String TYPE_ASSOCIATION = "ASSOCIATION";
    public static final String TYPE_OTHER = "OTHER";

    /**
     * 权威类型 → 展示名。{@link LinkedHashMap} 保证迭代顺序 = 前端下拉的展示顺序。
     *
     * <p>「政府」在展示层写作「政府机关」（现存 13 行该类型数据的既有文案，沿用以免列表出现两套叫法）；
     * 「企业」把原先前端的「国有企业 / 民营企业」两档**按规格归并**为一档 —— 实测库内不存在这两个取值，
     * 故无需数据回填，种子脚本已同步改为 canonical。</p>
     */
    private static final Map<String, String> TYPES = new LinkedHashMap<>();

    static {
        TYPES.put(TYPE_GOVERNMENT, "政府机关");
        TYPES.put(TYPE_ENTERPRISE, "企业");
        TYPES.put(TYPE_INSTITUTION, "事业单位");
        TYPES.put(TYPE_ASSOCIATION, "社会组织");
        TYPES.put(TYPE_OTHER, "其他");
    }

    /** 权威清单（只读，顺序即展示顺序）。 */
    public static Map<String, String> types() {
        return Collections.unmodifiableMap(TYPES);
    }

    /** 是否为合法机构类型。 */
    public static boolean isValidType(String orgType) {
        return orgType != null && TYPES.containsKey(orgType);
    }

    /**
     * 归一化 + 校验机构类型，返回 canonical 值；不合法时抛可直接展示的 400。
     *
     * <p><b>不做静默降级</b>：未知取值一律拒绝并在文案里带上可选清单，
     * 而不是「猜一个类型写进去」——猜错会把统计口径悄悄改掉（铁律 #2 的同族要求）。</p>
     */
    public static String requireOrgType(String raw) {
        String t = raw == null ? "" : raw.trim().toUpperCase(Locale.ROOT);
        if (!TYPES.containsKey(t)) {
            throw BizException.badRequest("机构类型不合法：" + raw
                    + "；可选值：" + String.join(" / ", TYPES.keySet()));
        }
        return t;
    }

    /** 入驻第 8 步完成即闭环 */
    public static final int ONBOARD_DONE = 8;


    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String name;

    private String code;

    private String orgType;

    private String creditCode;

    private String legalPerson;

    private String contactMobile;

    private String contactEmail;

    private Long adminUserId;

    private String adminName;

    private String status;

    private LocalDate establishedAt;

    private Integer onboardStep;

    private String remark;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    private Long createdBy;

    @TableLogic
    private LocalDateTime deletedAt;
}
