package cn.aioa.integration.scfy.contract;

import java.util.List;

/**
 * 一个 scfy 接口的契约（唯一事实源）。
 *
 * <p>本 record 是「文档声称」与「生产实测」<strong>合并后</strong>的结果，不是文档的翻译。
 * 合并规则：<b>凡实测与文档冲突，一律以实测为准，并在 {@link #note()} 记下冲突内容</b>。
 * 冲突记录不是注释，是数据 —— 它会被工具 description 与审计日志消费。</p>
 *
 * @param id      工具编码后缀（全局唯一），命名形如 {@code inheritor_list_by_area}
 * @param group   能力域，用于管理端分组与排查：传承人 / 项目 / 工坊 / 保护区 / 旅游
 * @param prefix  接口前缀，如 {@code /show/inheritor}
 * @param path    接口路径，如 {@code /getInheritorListByArea}
 * @param summary 一句话说明「这个接口回答什么问题」——供模型判断何时调用，不是接口名直译
 * @param params  参数契约（实测校正后）
 * @param status  可用性：{@link Status#AVAILABLE} / {@link Status#DEPRECATED}
 * @param note    实测说明或废弃原因；AVAILABLE 且无异常时为空
 */
public record ScfyEndpoint(String id,
                           String group,
                           String prefix,
                           String path,
                           String summary,
                           List<ScfyParam> params,
                           Status status,
                           String note) {

    public enum Status {
        /** 生产实测可用（HTTP 200 且 code=0）。 */
        AVAILABLE,
        /**
         * 已废弃，不注册为工具。
         * <p>废弃不是「暂不接入」：登记在此是为了让下一个人知道
         * <b>为什么不能接</b>，而不是重新踩一遍。</p>
         */
        DEPRECATED
    }

    /** 完整路径（不含 baseUrl），如 {@code /show/inheritor/getInheritorDetail}。 */
    public String fullPath() {
        return prefix + path;
    }

    public boolean available() {
        return status == Status.AVAILABLE;
    }

    /** 必填参数名列表，供缺参追问话术使用。 */
    public List<String> requiredParamNames() {
        return params.stream().filter(ScfyParam::required).map(ScfyParam::name).toList();
    }

    public ScfyParam param(String name) {
        return params.stream().filter(p -> p.name().equals(name)).findFirst().orElse(null);
    }

    /** 是否存在「文档与实测不符」的字段 —— 有则工具描述里必须显式提示模型。 */
    public boolean hasDocMismatch() {
        return params.stream().anyMatch(p -> p.docNote() != null && !p.docNote().isBlank());
    }

    public static ScfyEndpoint available(String id, String group, String prefix, String path,
                                         String summary, List<ScfyParam> params) {
        return new ScfyEndpoint(id, group, prefix, path, summary, params, Status.AVAILABLE, null);
    }

    public static ScfyEndpoint deprecated(String id, String group, String prefix, String path,
                                          String summary, String reason) {
        return new ScfyEndpoint(id, group, prefix, path, summary, List.of(),
                Status.DEPRECATED, reason);
    }
}
