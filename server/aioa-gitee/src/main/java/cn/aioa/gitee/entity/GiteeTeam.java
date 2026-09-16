package cn.aioa.gitee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 部门 ↔ Gitee 组织团队（部门隔离的落点）。
 *
 * <p>表 {@code gitee_team}（V48）。</p>
 *
 * <p><b>为什么需要 provider 字段</b>：需求原意是「每个部门对应 Gitee 组织内一个 Team」，
 * 但**实测 gitee.com 的 V5 API 没有组织级团队接口**（{@code /orgs/{org}/teams} 返回 HTML 404，
 * 详见 docs/30 §2）。因此部门隔离改为三重落地：</p>
 * <ol>
 *   <li>{@code namespace}：该部门仓库的命名前缀 —— 开源版可用的可观测隔离；</li>
 *   <li>{@code giteeTeamId}：企业版 / 未来 API 开放时把仓库真正挂到团队下
 *       （仓库级 {@code PUT /repos/{o}/{r}/teams/{team}} 实测存在）；</li>
 *   <li>协作者权限：见 {@link GiteeRepoMember}，跨部门成员必须被显式加为协作者。</li>
 * </ol>
 * <p>provider = {@code NAMESPACE}（默认）或 {@code API}。</p>
 */
@Data
@TableName("gitee_team")
public class GiteeTeam {

    public static final String PROVIDER_NAMESPACE = "NAMESPACE";
    public static final String PROVIDER_API = "API";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 平台部门 id（org_department.id）。 */
    private Long departmentId;

    /** Gitee 总组织 login。 */
    private String orgName;

    /** 团队显示名（默认取部门名）。 */
    private String teamName;

    /** 仓库命名前缀，部门隔离的可观测落点。 */
    private String namespace;

    /** Gitee 组织团队 id；NAMESPACE 模式下为空。 */
    private Long giteeTeamId;

    /** NAMESPACE / API。 */
    private String provider;

    /** 1 = 已在 Gitee 侧真正建好（仅 API 模式有意义）。 */
    private Boolean provisioned;

    private String remark;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @TableLogic
    private LocalDateTime deletedAt;
}
