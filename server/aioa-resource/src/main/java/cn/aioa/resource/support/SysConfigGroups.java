package cn.aioa.resource.support;

import cn.aioa.resource.entity.SysConfig;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 系统参数分组中文名（界面展示顺序）。
 *
 * <p><b>单一事实源</b>：此前散落在 {@code AdminConfigController.GROUP_NAMES}，而机构作用域参数页
 * （{@code OrgConfigController}）也要展示同一套中文分组名。两页若不共用同一份清单，就会出现
 * 「同一分组码两处中文名」的漂移（铁律 #1 的同类隐患）。故抽到此处，两处共用。</p>
 *
 * <p>顺序即界面展示顺序，必须用插入序 Map（{@code LinkedHashMap}）——
 * 不能用 {@code Map.of(...)}（它无序，会让分组标题乱序）。</p>
 */
public final class SysConfigGroups {

    /** 分组码 → 中文名（展示顺序 = 插入序）。 */
    public static final Map<String, String> NAMES = Collections.unmodifiableMap(new LinkedHashMap<>() {{
        put(SysConfig.GROUP_CONVERSATION, "会话与模型");
        put(SysConfig.GROUP_QUOTA, "额度与计费");
        put(SysConfig.GROUP_KNOWLEDGE, "知识库");
        put(SysConfig.GROUP_SECURITY, "安全合规");
        // V34 的 approval.tenant.content 用 AUDIT 分组。此前未登记 ⇒ 它落在「库里有、
        // grouped 里没有、界面看不见」的盲区（前端分组下拉亦由此清单驱动）。
        put(SysConfig.GROUP_AUDIT, "审核");
        put(SysConfig.GROUP_COMMON, "通用");
    }});

    private SysConfigGroups() {
    }
}
