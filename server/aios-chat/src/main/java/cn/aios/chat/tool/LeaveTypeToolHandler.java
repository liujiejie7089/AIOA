package cn.aios.chat.tool;

import cn.aios.org.entity.LeaveType;
import cn.aios.org.service.LeaveService;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 「假种目录」工具（2026-11-03）。
 *
 * <p>发起请假必须先选假种，而假种码是**租户自定义**的（annual / personal / sick …）。
 * 没有这个工具时，模型只能猜码值，猜错会被服务端拒（"假种不存在：xxx"），
 * 用户被迫来回改 —— 属于典型的「信息本来就在库里，却让模型去猜」。</p>
 *
 * <p>只返回启用中的假种：停用假种即使被选中也会在提交时被拒，提前过滤掉能少一轮往返。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LeaveTypeToolHandler implements ExternalToolHandler {

    public static final String TOOL = "list_leave_types";

    private final LeaveService leaveService;

    @Override
    public String name() {
        return TOOL;
    }

    @Override
    public String description() {
        return "列出本租户可用的请假假种（编码 / 名称 / 是否需要证明 / 单次最长天数 / 需提前天数）。"
                + "发起请假前先用本工具确认 leaveTypeCode，不要凭空编造假种码。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        Long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        List<LeaveType> types = leaveService.listTypes(tenantId);
        List<Map<String, Object>> out = new ArrayList<>(types.size());
        for (LeaveType t : types) {
            if (!"ENABLED".equalsIgnoreCase(String.valueOf(t.getStatus()))) {
                continue;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("code", t.getCode());
            row.put("name", t.getName());
            row.put("needProof", Boolean.TRUE.equals(t.getNeedProof()));
            row.put("maxConsecutiveDays", t.getMaxConsecutiveDays());
            row.put("advanceDays", t.getAdvanceDays());
            row.put("quotaDaysPerYear", t.getQuotaDaysPerYear());
            out.add(row);
        }
        log.info("list_leave_types: tenant={} => {} 个启用假种", tenantId, out.size());
        return Map.of("ok", true, "data", out);
    }
}
