package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.ApprovalFlowDef;
import cn.aioa.org.mapper.ApprovalFlowDefMapper;
import cn.aioa.resource.entity.WorkerCapability;
import cn.aioa.resource.mapper.WorkerCapabilityMapper;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 数字人能力声明服务（docs/52 P1/P3）。
 *
 * <p>职责：按 worker 列能力、批量保存（先软删旧行再插新行，同一事务）、给 intake 预检用的
 * {@link #checkCapabilities}（每个 form_code 必须存在且 ACTIVE、每个 tool_name 必须已注册、
 * approval_biz_type 必须有 ACTIVE 审批流定义）。</p>
 */
@Service
@RequiredArgsConstructor
public class WorkerCapabilityService {

    private final WorkerCapabilityMapper capabilityMapper;
    private final FormTemplateService templateService;
    private final ToolGatewayService toolGatewayService;
    private final ApprovalFlowDefMapper approvalFlowDefMapper;

    /** 能力声明入参（单条）。 */
    public record CapabilitySave(String taskCode, String taskName, String formCode,
                                 List<String> toolNames, String approvalBizType,
                                 Integer sort, Integer enabled) {
    }

    /** precheck 单条请求。 */
    public record CapabilityReq(String formCode, List<String> toolNames, String approvalBizType) {
    }

    /** 按 worker 列能力（活行）。 */
    public List<WorkerCapability> listByWorker(Long workerId) {
        return capabilityMapper.selectList(new LambdaQueryWrapper<WorkerCapability>()
                .eq(WorkerCapability::getWorkerId, workerId)
                .orderByAsc(WorkerCapability::getSort)
                .orderByAsc(WorkerCapability::getId));
    }

    /**
     * 按多个 worker 批量列能力（只取启用中，{@code enabled} 为 null 或 <>0 视为启用）。
     *
     * <p>转交（handoff）场景用：一次查出本租户候选数字人的全部能力行，避免 N 次查询。
     * 空入参直接返回 {@link List#of()}（不触库）。结果按 sort / id 升序，与单 worker 口径一致。</p>
     */
    public List<WorkerCapability> listByWorkers(Collection<Long> workerIds) {
        if (workerIds == null || workerIds.isEmpty()) {
            return List.of();
        }
        return capabilityMapper.selectList(new LambdaQueryWrapper<WorkerCapability>()
                .in(WorkerCapability::getWorkerId, workerIds)
                .and(w -> w.isNull(WorkerCapability::getEnabled).or().ne(WorkerCapability::getEnabled, 0))
                .orderByAsc(WorkerCapability::getSort)
                .orderByAsc(WorkerCapability::getId));
    }

    /**
     * 批量保存某 worker 的能力：先软删旧行再插新行，同一事务。
     *
     * @param items 新能力清单（覆盖式：传入即全量）
     */
    @Transactional(rollbackFor = Exception.class)
    public void saveBatch(Long tenantId, Long workerId, List<CapabilitySave> items, Long operatorId) {
        // 落库前先校验：依赖（表单/工具/审批流）不可用则直接拒绝，绝不能「先落库再校验」。
        List<CapabilityReq> reqs = List.of();
        if (items != null) {
            reqs = items.stream()
                    .map(it -> new CapabilityReq(it.formCode(), it.toolNames(), it.approvalBizType()))
                    .toList();
        }
        List<String> bad = checkCapabilities(tenantId, reqs);
        if (!bad.isEmpty()) {
            throw new BizException("能力校验未通过，已中止保存：" + String.join("；", bad));
        }
        // 先软删旧行（@TableLogic 自动置 deleted_at）
        capabilityMapper.delete(new LambdaQueryWrapper<WorkerCapability>()
                .eq(WorkerCapability::getWorkerId, workerId));
        if (items == null || items.isEmpty()) {
            return;
        }
        int sort = 0;
        for (CapabilitySave it : items) {
            WorkerCapability c = new WorkerCapability();
            c.setTenantId(tenantId);
            c.setWorkerId(workerId);
            c.setTaskCode(it.taskCode());
            c.setTaskName(it.taskName());
            c.setFormCode(it.formCode());
            // toolNames 用 Jackson 序列化成 JSON 数组
            try {
                c.setToolNamesJson(new com.fasterxml.jackson.databind.ObjectMapper()
                        .writeValueAsString(it.toolNames() == null ? List.of() : it.toolNames()));
            } catch (Exception e) {
                c.setToolNamesJson(null);
            }
            c.setApprovalBizType(it.approvalBizType());
            c.setSort(it.sort() != null ? it.sort() : sort++);
            c.setEnabled(it.enabled() != null ? it.enabled() : 1);
            c.setCreatedAt(LocalDateTime.now());
            c.setUpdatedAt(LocalDateTime.now());
            capabilityMapper.insert(c);
        }
    }

    /**
     * 能力预检（数字人创建第 7 项自检）：返回中文原因列表，空=全部通过。
     *
     * <ol>
     *   <li>每个 form_code 必须存在且 ACTIVE（本租户优先、回退平台默认）；</li>
     *   <li>每个 tool_name 必须已在工具注册表登记；</li>
     *   <li>approval_biz_type 非空时必须存在 ACTIVE 审批流定义。</li>
     * </ol>
     */
    public List<String> checkCapabilities(Long tenantId, List<CapabilityReq> reqs) {
        List<String> reasons = new ArrayList<>();
        if (reqs == null || reqs.isEmpty()) {
            return reasons;
        }
        Set<String> registeredTools = toolGatewayService.listTools().stream()
                .map(m -> {
                    Object fn = m.get("function");
                    if (fn instanceof Map<?, ?> fm) {
                        Object name = fm.get("name");
                        return name == null ? null : name.toString();
                    }
                    return null;
                })
                .filter(java.util.Objects::nonNull)
                .collect(Collectors.toSet());

        Set<String> checkedForms = new HashSet<>();
        for (CapabilityReq req : reqs) {
            if (req.formCode() == null || req.formCode().isBlank()) {
                reasons.add("能力缺少 form_code（表单码）");
                continue;
            }
            if (checkedForms.add(req.formCode()) && templateService.getByCode(tenantId, req.formCode()) == null) {
                reasons.add("表单码「" + req.formCode() + "」不存在或未启用");
            }
            if (req.toolNames() != null) {
                for (String tool : req.toolNames()) {
                    if (tool == null || tool.isBlank()) {
                        continue;
                    }
                    if (!registeredTools.contains(tool)) {
                        reasons.add("工具「" + tool + "」未注册（form_code=" + req.formCode() + "）");
                    }
                }
            }
            String biz = req.approvalBizType();
            if (biz != null && !biz.isBlank()) {
                long defCount = approvalFlowDefMapper.selectCount(new LambdaQueryWrapper<ApprovalFlowDef>()
                        .eq(ApprovalFlowDef::getTenantId, tenantId)
                        .eq(ApprovalFlowDef::getBizType, biz)
                        .eq(ApprovalFlowDef::getStatus, "ACTIVE"));
                if (defCount == 0) {
                    reasons.add("审批流「" + biz + "」没有 ACTIVE 定义（form_code=" + req.formCode() + "）");
                }
            }
        }
        return reasons;
    }
}
