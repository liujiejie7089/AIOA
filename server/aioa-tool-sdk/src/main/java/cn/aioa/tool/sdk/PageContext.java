package cn.aioa.tool.sdk;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 子应用经 SDK 上报的页面上下文快照（M1 仅定义契约，M2 起由 SDK 与网关联用）。
 */
@Data
public class PageContext {

    private String appCode;
    private String page;
    private String pageTitle;
    private String entityType;
    private String entityId;
    private Map<String, Object> filters;
    private List<String> selection;
}
