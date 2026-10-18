package cn.aios.resource.support;

import cn.aios.security.PermissionCatalog;

/**
 * 数字人「角色画像」—— 把 {@code agent_worker.worker_type} 解析成展示名 / 职责 / 边界 / 所需权限的**唯一判定点**。
 *
 * <p><b>为什么需要它</b>：{@link WorkerRole} 是枚举，只有 4 个硬编码角色，且
 * {@link WorkerRole#of(String)} 对未知取值**静默降级为 {@code GENERAL}**。而 OA 模块数字人
 * （{@code worker_type = OA_*}，见 V83）是数据行的，不走枚举 —— 若照旧用 {@code WorkerRole.of}
 * 解析，43 个模块数字人会被一律说成「通用办公助手」，系统提示里的职责边界也跟着错。</p>
 *
 * <p><b>口径</b>：</p>
 * <ul>
 *   <li>能解析成枚举常量（含大小写差异）→ 完全按枚举走，行为与改动前逐字一致；</li>
 *   <li>解析不到、但确有取值 → 视为「数据驱动的模块数字人」：展示名与职责取行内
 *       {@code name}/{@code description}（缺省回落到类型码），所需权限按通用对话计
 *       （模块数字人是平台预置资产，创建时不走权限准入门）；</li>
 *   <li>空值 → GENERAL（与 {@link WorkerRole#of} 一致，兼容 V21 之前的历史行）。</li>
 * </ul>
 */
public record WorkerProfile(String code, String roleName, String duty, String boundary, String permission) {

    public static WorkerProfile of(String workerType, String name, String description) {
        WorkerRole role = WorkerRole.of(workerType);
        boolean unknown = role == WorkerRole.GENERAL
                && workerType != null && !workerType.isBlank()
                && !WorkerRole.GENERAL.name().equalsIgnoreCase(workerType.trim());
        if (!unknown) {
            return new WorkerProfile(role.code(), role.displayName(), role.duty(), role.boundary(),
                    role.requiredPermission());
        }
        String code = workerType.trim().toUpperCase();
        String shown = name == null || name.isBlank() ? code : name.trim();
        // 「角色类型」在系统提示里紧跟在数字人名称之后出现，去掉重复后缀：
        // 「你是数字员工「公文助手数字人」（角色类型：公文助手）」而不是「（角色类型：公文助手数字人）」。
        String roleName = shown.endsWith("数字人") ? shown.substring(0, shown.length() - 3).trim() : shown;
        String scope = description == null || description.isBlank() ? shown : description.trim();
        // duty 保留整段（含「；不含…」）—— 它是系统提示里「唯一可回答的范围」的原文，
        // 拆掉反向边界会让模型重新开始答职责外的问题。boundary 另取该段供「能力边界卡」展示。
        int cut = scope.indexOf("；不含");
        String boundary = cut > 0 ? scope.substring(cut + 1) : "";
        return new WorkerProfile(code, roleName.isBlank() ? shown : roleName, scope, boundary,
                PermissionCatalog.CHAT_BASIC);
    }
}
