package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.mapper.SysConfigMapper;
import cn.aioa.resource.service.ActivityLogService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 系统参数配置（管理端，V18 / 技术方案 5.2）：
 * 面向租户管理员的运行期可调参数，覆盖会话与模型、额度与计费、知识库、安全合规四组。
 *
 * <p>租户隔离：首次读取时若本租户无参数，自动从平台默认（tenant_id=0）克隆一份；
 * 平台默认缺失时回退到代码内置默认表，保证任何环境开箱即可用。</p>
 *
 * GET  /api/v1/admin/configs[?q=&group=]   列表（按分组聚合）
 * PUT  /api/v1/admin/configs/{key}         更新单个参数（body: {value}）
 * PUT  /api/v1/admin/configs               批量更新（body: {items:[{key,value}]}）
 * POST /api/v1/admin/configs/{key}/reset   恢复出厂默认
 * POST /api/v1/admin/configs/reset         全部恢复默认
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/admin/configs")
@RequiredArgsConstructor
public class AdminConfigController {

    /** 分组中文名 */
    private static final Map<String, String> GROUP_NAMES = new LinkedHashMap<>() {{
        put(SysConfig.GROUP_CONVERSATION, "会话与模型");
        put(SysConfig.GROUP_QUOTA, "额度与计费");
        put(SysConfig.GROUP_KNOWLEDGE, "知识库");
        put(SysConfig.GROUP_SECURITY, "安全合规");
        put(SysConfig.GROUP_COMMON, "通用");
    }};

    /** 代码内置兜底默认（平台默认表缺失时使用，保证开箱可用） */
    private static final List<SysConfig> BUILTIN_DEFAULTS = builtinDefaults();

    private final SysConfigMapper mapper;
    private final ActivityLogService activityLogService;

    private AuthUser requireAdmin() {
        AuthUser user = AuthUserContext.require();
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("系统参数配置仅租户管理员可操作");
        }
        return user;
    }

    // ---------------- 查询 ----------------

    @GetMapping
    public ApiResponse<Map<String, Object>> list(@RequestParam(name = "q", required = false) String q,
                                                 @RequestParam(name = "group", required = false) String group) {
        AuthUser user = requireAdmin();
        List<SysConfig> rows = loadTenantConfigs(user.getTenantId());
        List<SysConfig> filtered = rows.stream()
                .filter(c -> group == null || group.isBlank() || group.equalsIgnoreCase(c.getGroupCode()))
                .filter(c -> {
                    if (q == null || q.isBlank()) return true;
                    String kw = q.trim().toLowerCase();
                    return contains(c.getConfigKey(), kw) || contains(c.getConfigName(), kw)
                            || contains(c.getDescription(), kw);
                })
                .sorted(Comparator.comparing(SysConfig::getGroupCode).thenComparing(SysConfig::getSortNo))
                .collect(Collectors.toList());

        // 按分组聚合，方便前端直接渲染
        Map<String, List<SysConfig>> grouped = new LinkedHashMap<>();
        for (Map.Entry<String, String> e : GROUP_NAMES.entrySet()) {
            List<SysConfig> items = filtered.stream()
                    .filter(c -> e.getKey().equals(c.getGroupCode()))
                    .collect(Collectors.toList());
            if (!items.isEmpty()) {
                grouped.put(e.getKey(), items);
            }
        }

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("groups", GROUP_NAMES);
        data.put("items", filtered);
        data.put("grouped", grouped);
        data.put("total", filtered.size());
        return ApiResponse.ok(data);
    }

    // ---------------- 更新 ----------------

    @PutMapping("/{key}")
    @Transactional
    public ApiResponse<SysConfig> updateOne(@PathVariable("key") String key, @RequestBody Map<String, Object> body) {
        AuthUser user = requireAdmin();
        String value = body.get("value") == null ? null : String.valueOf(body.get("value"));
        SysConfig row = updateValue(user, key, value);
        return ApiResponse.ok(row);
    }

    @PutMapping
    @Transactional
    public ApiResponse<Map<String, Object>> updateBatch(@RequestBody Map<String, Object> body) {
        AuthUser user = requireAdmin();
        Object raw = body.get("items");
        if (!(raw instanceof List<?> items) || items.isEmpty()) {
            throw BizException.badRequest("请提供 items 数组，如 {items:[{key,value}]}");
        }
        List<String> changed = new ArrayList<>();
        List<String> rejected = new ArrayList<>();
        for (Object o : items) {
            if (!(o instanceof Map<?, ?> m)) {
                rejected.add("非法条目：" + o);
                continue;
            }
            String key = m.get("key") == null ? null : String.valueOf(m.get("key"));
            Object v = m.get("value");
            if (key == null || key.isBlank()) {
                rejected.add("缺少参数键");
                continue;
            }
            try {
                updateValue(user, key, v == null ? null : String.valueOf(v));
                changed.add(key);
            } catch (BizException e) {
                rejected.add(key + "：" + e.getMessage());
            }
        }
        if (changed.isEmpty() && !rejected.isEmpty()) {
            throw BizException.badRequest("全部参数校验失败 → " + String.join("；", rejected));
        }
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("changed", changed);
        data.put("rejected", rejected);
        return ApiResponse.ok(data);
    }

    @PostMapping("/{key}/reset")
    @Transactional
    public ApiResponse<SysConfig> resetOne(@PathVariable("key") String key) {
        AuthUser user = requireAdmin();
        SysConfig cur = requireOwned(user, key);
        String dv = cur.getDefaultValue() != null ? cur.getDefaultValue() : cur.getConfigValue();
        validateValue(cur, dv);
        cur.setConfigValue(dv);
        cur.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(cur);
        activityLogService.record(user.getTenantId(), user.getUserId(), "CONFIG_RESET",
                "ok", "恢复默认 " + cur.getConfigName() + " = " + dv);
        return ApiResponse.ok(cur);
    }

    @PostMapping("/reset")
    @Transactional
    public ApiResponse<Map<String, Object>> resetAll() {
        AuthUser user = requireAdmin();
        List<SysConfig> rows = loadTenantConfigs(user.getTenantId());
        int n = 0;
        for (SysConfig c : rows) {
            if (Boolean.FALSE.equals(c.getEditable())) continue;
            String dv = c.getDefaultValue() != null ? c.getDefaultValue() : c.getConfigValue();
            c.setConfigValue(dv);
            c.setUpdatedAt(LocalDateTime.now());
            mapper.updateById(c);
            n++;
        }
        activityLogService.record(user.getTenantId(), user.getUserId(), "CONFIG_RESET_ALL",
                "ok", "全部参数恢复默认，共 " + n + " 项");
        return ApiResponse.ok(Map.of("reseted", n));
    }

    // ---------------- 内部 ----------------

    private SysConfig updateValue(AuthUser user, String key, String value) {
        SysConfig cur = requireOwned(user, key);
        if (Boolean.FALSE.equals(cur.getEditable())) {
            throw BizException.badRequest("参数「" + cur.getConfigName() + "」为只读项，不可修改");
        }
        if (value == null) {
            throw BizException.badRequest("参数值不能为空");
        }
        String normalized = normalize(cur, value);
        validateValue(cur, normalized);
        String old = cur.getConfigValue();
        if (normalized.equals(old)) {
            return cur;
        }
        cur.setConfigValue(normalized);
        cur.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(cur);
        activityLogService.record(user.getTenantId(), user.getUserId(), "CONFIG_UPDATE",
                "ok", "修改 " + cur.getConfigName() + "：" + old + " → " + normalized);
        return cur;
    }

    /** 按类型归一化：BOOL 统一 true/false；数值去空白。 */
    private String normalize(SysConfig cfg, String value) {
        String v = value.trim();
        if (SysConfig.TYPE_BOOL.equalsIgnoreCase(cfg.getValueType())) {
            if (Set.of("true", "1", "yes", "y", "on", "是", "开").contains(v.toLowerCase())) return "true";
            if (Set.of("false", "0", "no", "n", "off", "否", "关").contains(v.toLowerCase())) return "false";
        }
        return v;
    }

    /** 类型 + 范围校验。 */
    private void validateValue(SysConfig cfg, String value) {
        String type = cfg.getValueType() == null ? SysConfig.TYPE_STRING : cfg.getValueType().toUpperCase();
        if (SysConfig.TYPE_INT.equals(type) || SysConfig.TYPE_DECIMAL.equals(type)) {
            BigDecimal num;
            try {
                num = new BigDecimal(value.trim());
            } catch (Exception e) {
                throw BizException.badRequest("「" + cfg.getConfigName() + "」需为数值，当前：" + value);
            }
            if (SysConfig.TYPE_INT.equals(type) && num.stripTrailingZeros().scale() > 0) {
                throw BizException.badRequest("「" + cfg.getConfigName() + "」需为整数，当前：" + value);
            }
            if (cfg.getMinValue() != null && num.compareTo(cfg.getMinValue()) < 0) {
                throw BizException.badRequest("「" + cfg.getConfigName() + "」不能小于 " + plain(cfg.getMinValue()));
            }
            if (cfg.getMaxValue() != null && num.compareTo(cfg.getMaxValue()) > 0) {
                throw BizException.badRequest("「" + cfg.getConfigName() + "」不能大于 " + plain(cfg.getMaxValue()));
            }
        } else if (SysConfig.TYPE_BOOL.equals(type)) {
            if (!Set.of("true", "false").contains(value.trim().toLowerCase())) {
                throw BizException.badRequest("「" + cfg.getConfigName() + "」需为布尔值（true/false）");
            }
        } else if (value.length() > 500) {
            throw BizException.badRequest("「" + cfg.getConfigName() + "」长度不能超过 500 字符");
        }
    }

    private static String plain(BigDecimal v) {
        return v.stripTrailingZeros().toPlainString();
    }

    private SysConfig requireOwned(AuthUser user, String key) {
        return loadTenantConfigs(user.getTenantId()).stream()
                .filter(c -> key.equals(c.getConfigKey()))
                .findFirst()
                .orElseThrow(() -> BizException.notFound("参数不存在：" + key));
    }

    /**
     * 读取本租户参数；若为空则从平台默认（tenant_id=0）克隆，仍为空则用内置默认表初始化。
     */
    private List<SysConfig> loadTenantConfigs(Long tenantId) {
        List<SysConfig> rows = mapper.selectList(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, tenantId)
                .orderByAsc(SysConfig::getGroupCode)
                .orderByAsc(SysConfig::getSortNo));
        if (!rows.isEmpty()) {
            return rows;
        }
        // 首次访问：克隆平台默认 → 内置默认
        List<SysConfig> templates = mapper.selectList(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, 0L)
                .orderByAsc(SysConfig::getGroupCode)
                .orderByAsc(SysConfig::getSortNo));
        if (templates.isEmpty()) {
            templates = BUILTIN_DEFAULTS;
        }
        List<SysConfig> cloned = new ArrayList<>();
        for (SysConfig t : templates) {
            SysConfig row = new SysConfig();
            row.setTenantId(tenantId);
            row.setConfigKey(t.getConfigKey());
            row.setConfigValue(t.getDefaultValue() != null ? t.getDefaultValue() : t.getConfigValue());
            row.setValueType(t.getValueType());
            row.setGroupCode(t.getGroupCode());
            row.setConfigName(t.getConfigName());
            row.setDescription(t.getDescription());
            row.setUnit(t.getUnit());
            row.setDefaultValue(t.getDefaultValue());
            row.setMinValue(t.getMinValue());
            row.setMaxValue(t.getMaxValue());
            row.setEditable(t.getEditable() == null ? Boolean.TRUE : t.getEditable());
            row.setSortNo(t.getSortNo() == null ? 0 : t.getSortNo());
            row.setCreatedAt(LocalDateTime.now());
            try {
                mapper.insert(row);
                cloned.add(row);
            } catch (Exception e) {
                // 并发克隆冲突（唯一键）→ 忽略，回读已有
                log.debug("clone sys_config skipped: {}", e.getMessage());
            }
        }
        if (!cloned.isEmpty()) {
            return cloned;
        }
        return mapper.selectList(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, tenantId)
                .orderByAsc(SysConfig::getGroupCode)
                .orderByAsc(SysConfig::getSortNo));
    }

    private static boolean contains(String s, String kw) {
        return s != null && s.toLowerCase().contains(kw);
    }

    private static List<SysConfig> builtinDefaults() {
        List<SysConfig> list = new ArrayList<>();
        list.add(d("chat.context_rounds", "10", SysConfig.TYPE_INT, SysConfig.GROUP_CONVERSATION,
                "单会话上下文轮数上限", "同一会话保留的上下文轮数，超出后自动摘要压缩（P0 FR-D2）", "轮", "10", "1", "100", 10));
        list.add(d("chat.first_token_ms", "2000", SysConfig.TYPE_INT, SysConfig.GROUP_CONVERSATION,
                "首字延迟目标", "流式输出端到端首字延迟门禁（P0 FR-D1）", "毫秒", "2000", "500", "10000", 20));
        list.add(d("chat.max_steps", "8", SysConfig.TYPE_INT, SysConfig.GROUP_CONVERSATION,
                "智能体最大推理步数", "单轮任务主循环最大步数（架构设计 5）", "步", "8", "1", "32", 30));
        list.add(d("chat.default_model_route", "auto", SysConfig.TYPE_STRING, SysConfig.GROUP_CONVERSATION,
                "默认模型路由", "auto=平台智能路由；亦可指定已上架模型标识（P0 FR-D4）", "", "auto", null, null, 40));
        list.add(d("quota.low_balance_percent", "20", SysConfig.TYPE_DECIMAL, SysConfig.GROUP_QUOTA,
                "额度低余额提醒阈值", "剩余额度占比低于该值时卡片变色提醒（P0 FR-G1）", "%", "20", "0", "100", 10));
        list.add(d("quota.daily_free_tokens", "20000", SysConfig.TYPE_INT, SysConfig.GROUP_QUOTA,
                "每人每日免费词元", "普通用户每日发放的免费词元数（P0 FR-B2）", "词元", "20000", "0", "10000000", 20));
        list.add(d("quota.alert_enabled", "true", SysConfig.TYPE_BOOL, SysConfig.GROUP_QUOTA,
                "额度提醒开关", "关闭后用户端不再展示低余额变色与提示", "", "true", null, null, 30));
        list.add(d("kb.max_file_mb", "50", SysConfig.TYPE_INT, SysConfig.GROUP_KNOWLEDGE,
                "单文件上传上限", "单个知识库/资料文件大小上限（P0 FR-F1）", "MB", "50", "1", "2048", 10));
        list.add(d("kb.chunk_size", "800", SysConfig.TYPE_INT, SysConfig.GROUP_KNOWLEDGE,
                "切片长度", "RAG 入库时单切片的目标字符数", "字符", "800", "100", "4000", 20));
        list.add(d("kb.top_k", "5", SysConfig.TYPE_INT, SysConfig.GROUP_KNOWLEDGE,
                "检索召回条数", "问答检索返回的切片条数（引用溯源条目上限）", "条", "5", "1", "20", 30));
        list.add(d("kb.citation_required", "true", SysConfig.TYPE_BOOL, SysConfig.GROUP_KNOWLEDGE,
                "强制引用溯源", "开启后引用知识库的回答必须附来源条目（P0 4.1）", "", "true", null, null, 40));
        list.add(d("security.content_double_check", "true", SysConfig.TYPE_BOOL, SysConfig.GROUP_SECURITY,
                "内容双审开关", "输入与输出均过内容安全审核（P0 FR-H3）", "", "true", null, null, 10));
        list.add(d("security.audit_retention_years", "3", SysConfig.TYPE_INT, SysConfig.GROUP_SECURITY,
                "留痕保存年限", "台账与操作留痕最少保存年限（P0 4.2）", "年", "3", "1", "30", 20));
        list.add(d("security.realname_required", "true", SysConfig.TYPE_BOOL, SysConfig.GROUP_SECURITY,
                "强制实名认证", "开启后未实名用户不可发起会话（P0 FR-A）", "", "true", null, null, 30));
        return list;
    }

    private static SysConfig d(String key, String value, String type, String group, String name,
                               String desc, String unit, String def, String min, String max, int sort) {
        SysConfig c = new SysConfig();
        c.setTenantId(0L);
        c.setConfigKey(key);
        c.setConfigValue(value);
        c.setValueType(type);
        c.setGroupCode(group);
        c.setConfigName(name);
        c.setDescription(desc);
        c.setUnit(unit);
        c.setDefaultValue(def);
        c.setMinValue(min == null ? null : new BigDecimal(min));
        c.setMaxValue(max == null ? null : new BigDecimal(max));
        c.setEditable(Boolean.TRUE);
        c.setSortNo(sort);
        return c;
    }
}
