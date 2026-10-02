package cn.aioa.project.support;

import java.util.Set;

/**
 * 项目类型常量与判定（BR-01 / BR-02 的唯一事实源）。
 *
 * <p><b>只有两个取值</b>，且它是「配置面」的总开关：{@link #DEV} 才允许代码仓库相关配置
 * （项目绑仓库、任务关联 issue/分支/提交）。前端据此渲染、后端据此校验 —— 两端都读这一个常量口径，
 * 不允许任何一处自己写字符串字面量（写死 {@code "DEV"} 的地方迟早会与这里漂移）。</p>
 */
public final class PmProjectType {

    /** 业务项目：只有业务字段，无任何代码仓库配置。 */
    public static final String BUSINESS = "BUSINESS";

    /** 开发项目：额外具备代码仓库绑定与任务仓库关联。 */
    public static final String DEV = "DEV";

    public static final Set<String> ALL = Set.of(BUSINESS, DEV);

    private PmProjectType() {
    }

    /** 是否合法类型。 */
    public static boolean isValid(String type) {
        return type != null && ALL.contains(type);
    }

    /** 是否为开发项目（仓库配置的允许条件）。 */
    public static boolean isDev(String type) {
        return DEV.equals(type);
    }
}
