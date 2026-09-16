package cn.aioa.org.support.approver;

import cn.aioa.org.entity.OrgDuty;
import cn.aioa.org.mapper.OrgDutyMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 审批人解析门面（四期）—— 把「审批人类型」路由到对应 {@link ApproverStrategy}。
 *
 * <p>引擎只依赖本类，不再认识任何具体求值口径；新增口径 = 新增一个策略 Bean，
 * 无需改动 {@code ApprovalFlowService}。</p>
 *
 * <p><b>为什么返回列表而不是单值</b>：职务型口径天然可能对应多个人（如部门有两位副职），
 * 把「多个人」这一事实在解析层就丢掉、只留第一个，会让五期的会签 / 抢占模式失去数据基础。
 * 解析层给出有序候选，消费层（{@code mode}）决定用几个 —— 两件事分层。</p>
 */
@Slf4j
@Component
public class ApproverResolver {

    private final OrgStatMapper statMapper;
    private final OrgDutyMapper dutyMapper;
    /** type → strategy（不可变视图，构造期一次性建好）。 */
    private final Map<String, ApproverStrategy> registry;

    public ApproverResolver(OrgStatMapper statMapper, OrgDutyMapper dutyMapper,
                            List<ApproverStrategy> strategies) {
        this.statMapper = statMapper;
        this.dutyMapper = dutyMapper;
        Map<String, ApproverStrategy> m = new LinkedHashMap<>();
        for (ApproverStrategy s : strategies) {
            ApproverStrategy prev = m.put(s.type(), s);
            if (prev != null) {
                // 同类型重复注册会让「谁生效」取决于 Bean 顺序 —— 属于配置错误，必须显式暴露。
                log.warn("审批人类型「{}」被重复注册（{} 覆盖 {}），请检查策略族定义",
                        s.type(), s.getClass().getSimpleName(), prev.getClass().getSimpleName());
            }
        }
        this.registry = Map.copyOf(m);
        log.info("审批人解析策略族已装载 {} 种类型：{}", registry.size(), registry.keySet());
    }

    /** 已注册的审批人类型（供配置校验：未注册类型 = 配置写错，不再静默兜底）。 */
    public Set<String> knownTypes() {
        return registry.keySet();
    }

    /**
     * 解析候选审批人。
     *
     * @return 有序候选；类型未注册或解析不到人时返回<b>空列表</b>（绝不返回 null，
     * 也绝不抛异常 —— 由调用方按「缺位」口径顺延并在单据上写明原因）
     */
    public List<ApproverStrategy.Candidate> resolve(String type, ApproverStrategy.Context ctx) {
        if (type == null || type.isBlank()) {
            return List.of();
        }
        ApproverStrategy s = registry.get(type);
        if (s == null) {
            log.warn("未注册的审批人类型「{}」，已按「解析不到」处理（可用类型：{}）", type, registry.keySet());
            return List.of();
        }
        List<ApproverStrategy.Candidate> list = s.resolve(ctx);
        if (list == null) {
            return List.of();
        }
        // 过滤脏候选（无 id），并保序去重：同一人只出现一次，否则会签会要求他批两次。
        Map<Long, ApproverStrategy.Candidate> uniq = new LinkedHashMap<>();
        for (ApproverStrategy.Candidate c : list) {
            if (c == null || c.userId() == null || c.userId() == 0L) {
                continue;
            }
            uniq.putIfAbsent(c.userId(), c);
        }
        // 统一在此补姓名：策略只负责「求到谁」，姓名留痕是解析门面的职责。
        // 这样策略之间不必互相依赖（否则会与门面构成循环依赖）。
        List<ApproverStrategy.Candidate> out = new ArrayList<>(uniq.size());
        for (ApproverStrategy.Candidate c : uniq.values()) {
            out.add(c.name() != null ? c
                    : new ApproverStrategy.Candidate(c.userId(), nameOf(c.userId()),
                            c.approverType(), c.dutyCode()));
        }
        return out;
    }

    /** 解析「部门负责人」的单一取值（兼容既有调用点：上级链 / 知会）。 */
    public Long deptLeader(Long tenantId, Long institutionId, Long departmentId,
                           boolean allowCrossDeptFallback) {
        List<ApproverStrategy.Candidate> c = resolve("DEPT_LEADER",
                new ApproverStrategy.Context(tenantId, institutionId, departmentId, null, null, null,
                        null, allowCrossDeptFallback));
        return c.isEmpty() ? null : c.get(0).userId();
    }

    /**
     * 职务码 → 中文名（租户职务字典）。
     *
     * <p>一次查全部需要的码，避免 timeline 逐节点查库。字典缺失时回落
     * {@link OrgDuty#nameOf(String)}（内置四职务的中文名），再退化为原码 —— 保证
     * 前端永远有可读文案，不会出现空白。</p>
     */
    public Map<String, String> dutyLabels(Long tenantId, java.util.Collection<String> codes) {
        Map<String, String> out = new LinkedHashMap<>();
        Set<String> need = new LinkedHashSet<>();
        if (codes != null) {
            for (String c : codes) {
                if (c != null && !c.isBlank()) {
                    need.add(c);
                }
            }
        }
        if (need.isEmpty()) {
            return out;
        }
        Map<String, String> fromDb = new LinkedHashMap<>();
        try {
            List<OrgDuty> rows = dutyMapper.selectList(new LambdaQueryWrapper<OrgDuty>()
                    .eq(OrgDuty::getTenantId, tenantId == null ? 0L : tenantId)
                    .in(OrgDuty::getCode, need));
            for (OrgDuty d : rows) {
                fromDb.put(d.getCode(), d.getName());
            }
        } catch (Exception e) {
            log.warn("读取职务字典失败，回落到内置职务名：{}", e.getMessage());
        }
        for (String c : need) {
            String name = fromDb.get(c);
            out.put(c, name != null && !name.isBlank() ? name : OrgDuty.nameOf(c));
        }
        return out;
    }

    /** 用户显示名（任务留痕用；查不到时退化为「用户#id」，不抛异常）。 */
    public String nameOf(Long userId) {
        if (userId == null) {
            return null;
        }
        Map<String, Object> u = statMapper.selectUserName(userId);
        return u == null || u.get("name") == null ? ("用户#" + userId) : String.valueOf(u.get("name"));
    }
}
