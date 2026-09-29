package cn.aioa.common.org;

/**
 * 机构状态 + 「运营面可见性」规则 —— <b>唯一权威</b>。
 *
 * <h3>为什么要单独抽出来</h3>
 * <p>机构表 {@code org_institution} 由 {@code aioa-org} 读写，但 {@code aioa-admin} 的
 * 「人员管理」用原生 SQL 读它（模块依赖方向：org 与 admin 互不依赖，只共享数据库表）。
 * 于是「已注销机构要退出哪些页面」这条规则天然会被写在两个模块里 ——
 * 而「同一判定点两处实现」正是本项目反复出现的头号缺陷类型（铁律 #1）。
 * 把常量与 SQL 片段收敛到 common，两边都从这里取。</p>
 *
 * <h3>规则本身</h3>
 * <p><b>注销（CLOSED）＝ 不可逆的法人档案终态</b>，它不再对外提供任何服务，
 * 因此必须退出<b>全部运营面</b>：机构管理清单 / 入驻进度 / 资源授权 / 费用分摊 /
 * 人员归属。档案行本身<b>不删除</b>（清理只有「删租户」一条路，见
 * {@code TenantDeleteService}），需要看档案的调用方必须<b>显式</b>声明
 * （{@code includeClosed=true}）。</p>
 *
 * <p>注意区分三个不同的事，它们此前常被混为一谈：</p>
 * <ul>
 *   <li><b>停用</b> {@link #SUSPENDED} —— 可恢复，仍在运营面（要能看到才能「恢复」）；</li>
 *   <li><b>注销</b> {@link #CLOSED} —— 不可恢复，退出运营面，行保留；</li>
 *   <li><b>申请删除</b> —— 真删，且必须过上一级审核（与状态字段无关，走审批单）。</li>
 * </ul>
 */
public final class InstitutionStatus {

    public static final String ACTIVE = "ACTIVE";
    public static final String SUSPENDED = "SUSPENDED";
    /** 注销：不可逆的法人档案终态，退出全部运营面。 */
    public static final String CLOSED = "CLOSED";

    private InstitutionStatus() {
    }

    /**
     * 该状态是否参与运营面展示。
     *
     * <p>{@code null}（历史行漏写状态）按「参与」处理：宁可多展示一个可疑行，
     * 也不能让真机构被静默判定成已注销而消失 —— 与
     * {@code TenantDeleteService.countLiveInstitutions} 的「宁可多拦」同向。</p>
     */
    public static boolean operational(String status) {
        return !CLOSED.equals(status);
    }

    /**
     * 运营面过滤的 SQL 片段，配合 {@code org_institution} 的别名使用。
     *
     * <p>与 {@link #operational(String)} 同义，供无法复用 Java 判定的原生 SQL 使用
     * （唯一使用点：{@code PersonnelService}）。</p>
     *
     * @param alias {@code org_institution} 在该查询里的别名（如 {@code x} / {@code i}）
     */
    public static String sqlOperational(String alias) {
        return "(" + alias + ".status IS NULL OR " + alias + ".status <> '" + CLOSED + "')";
    }
}
