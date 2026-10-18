package cn.aios.project.port;

import java.util.Map;

/**
 * 项目域对外的**只读窄接口**（跨模块端口）。供 {@code aios-chat} 在会话创建与 run 下发链路上
 * 使用项目维度，实现「用户端不同项目数据隔离」的服务端一半。
 *
 * <p><b>依赖方向</b>：只允许 {@code aios-chat → aios-project}（本接口 + 其适配器），
 * <b>禁止反向</b>——{@code aios-project} 绝不 import {@code cn.aios.chat.*}，避免模块环。</p>
 *
 * <p><b>为什么用端口而不是让 chat 自己写 SQL 查 pm_project_worker</b>：判定「某数字员工是否
 * 分配在某项目且启用」必须只有**一处**实现（{@link cn.aios.project.service.PmDigitalWorkerService}）。
 * 若 chat 侧另写一份查询，两处口径迟早在「停用 / 软删 / 多租户」的边界上漂移，
 * 于是「选择卡里看不到、却能直连建成会话」这类越权就会复活。</p>
 *
 * <p>本接口全部为只读、入参均为租户内主键（调用方须已完成可见性判定），不返回敏感字段。</p>
 */
public interface PmAiScopePort {

    /**
     * 数字员工是否**可用**于该项目：分配记录存在、未软删、且 {@code enabled=1}。
     *
     * <p>{@code projectId}/{@code workerId} 任一为空返回 false（无项目会话不做项目校验，
     * 由调用方决定是否跳过）。</p>
     */
    boolean isWorkerUsable(Long tenantId, Long projectId, Long workerId);

    /**
     * 项目生效上下文（只读结构）：字段与 {@code PmDigitalWorkerService.effectiveScope} 一致
     * （{@code projectId / workerId / projectDefault / workerSpecific / effective / effectiveCount}）。
     * 供 {@code RunService} 组装数字人 scope 下发。
     */
    Map<String, Object> effectiveScope(Long tenantId, Long projectId, Long workerId);

    /**
     * 当前项目简报（只读）：供 {@code RunService} 在「未绑定数字员工」的项目会话里也把项目上下文
     * 下发到 Agent，避免 Agent 反问「上传到哪个系统或平台」。
     *
     * <p>返回结构固定为 {@code {id, name, type, status}}（{@code type}=projectType）。</p>
     *
     * <p><b>不做鉴权、不抛 403</b>：调用方（{@code RunService}）已完成「该会话属于该租户的项目」
     * 这类可见性判定，本方法只负责把库里的项目名等字段原样取出。
     * 以下情形返回 {@code null}：{@code projectId} 为空 / 查不到 / 已软删（{@code deletedAt != null}）
     * / 租户不符。</p>
     */
    Map<String, Object> projectBrief(Long tenantId, Long projectId);
}
