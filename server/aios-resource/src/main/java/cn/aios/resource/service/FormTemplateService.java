package cn.aios.resource.service;

import cn.aios.common.exception.BizException;
import cn.aios.org.entity.LeaveType;
import cn.aios.org.service.LeaveService;
import cn.aios.resource.entity.FormTemplate;
import cn.aios.resource.entity.FormTemplateVersion;
import cn.aios.resource.mapper.FormTemplateMapper;
import cn.aios.resource.mapper.FormTemplateVersionMapper;
import cn.aios.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 表单定义服务（docs/52 P1）。
 *
 * <p>职责：取活行（含平台默认回退）、渲染成前端/agent 可用的 fields[]、保存/更新（自动升版并写快照）、列表。</p>
 */
@Service
@RequiredArgsConstructor
public class FormTemplateService {

    private static final Logger log = LoggerFactory.getLogger(FormTemplateService.class);

    private final FormTemplateMapper templateMapper;
    private final FormTemplateVersionMapper versionMapper;
    private final LeaveService leaveService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 保存表单定义的入参（管理端设计器提交）。 */
    public record FormSave(String code, String name, String moduleCode, String bizType,
                           String schemaJson, String layoutJson, String submitPolicy,
                           String receiptJson) {
    }

    /** 渲染后的单个字段（给前端/agent 用）。 */
    public record FormField(String name, String label, String type, boolean required,
                            List<Map<String, Object>> options, String placeholder,
                            Map<String, Object> validation, Object defaultVal) {
    }

    /** 渲染后的整张表单。 */
    public record FormRender(Long templateId, String code, String name, int version,
                             String moduleCode, String submitPolicy, List<FormField> fields) {
    }

    /**
     * 取某个表单的 ACTIVE 活行：优先本租户，本租户没有则回退 tenant_id=0 平台默认。
     *
     * @return 命中的活行；都不存在返回 null
     */
    public FormTemplate getByCode(Long tenantId, String code) {
        FormTemplate t = templateMapper.selectOne(new LambdaQueryWrapper<FormTemplate>()
                .eq(FormTemplate::getTenantId, tenantId)
                .eq(FormTemplate::getCode, code)
                .eq(FormTemplate::getStatus, FormTemplate.STATUS_ACTIVE)
                .last("limit 1"));
        if (t != null) {
            return t;
        }
        if (tenantId != null && tenantId != 0L) {
            return templateMapper.selectOne(new LambdaQueryWrapper<FormTemplate>()
                    .eq(FormTemplate::getTenantId, 0L)
                    .eq(FormTemplate::getCode, code)
                    .eq(FormTemplate::getStatus, FormTemplate.STATUS_ACTIVE)
                    .last("limit 1"));
        }
        return null;
    }

    /**
     * 当前租户可见的 ACTIVE 表单清单（给 agent 系统提示用）：{code,name,module_code,biz_type}。
     *
     * <p>口径：查 {@code form_template} 里 {@code status=ACTIVE} 且 {@code tenant_id in (tenantId, 0)}；
     * 本租户行优先于平台默认（tenant_id=0）行，按 code 去重（putIfAbsent，先放本租户的）。
     * 排序 module_code、code 升序；上限 200 条（超出截断并记一条 info）。
     * 只带上述四个键，绝不带 schema_json（避免把大字段灌进对话上下文）。</p>
     */
    public List<Map<String, Object>> listAvailable(Long tenantId) {
        LambdaQueryWrapper<FormTemplate> w = new LambdaQueryWrapper<FormTemplate>()
                .eq(FormTemplate::getStatus, FormTemplate.STATUS_ACTIVE);
        if (tenantId != null) {
            w.in(FormTemplate::getTenantId, tenantId, 0L);
        } else {
            w.eq(FormTemplate::getTenantId, 0L);
        }
        List<FormTemplate> rows = templateMapper.selectList(w);

        // 本租户行优先于平台默认：先放本租户，再放 tenant_id=0，putIfAbsent 保证留的是本租户行
        Map<String, Map<String, Object>> byCode = new LinkedHashMap<>();
        for (FormTemplate t : rows) {
            if (t.getTenantId() != null && t.getTenantId().equals(tenantId)) {
                byCode.putIfAbsent(t.getCode(), toFormInfo(t));
            }
        }
        for (FormTemplate t : rows) {
            if (t.getTenantId() == null || t.getTenantId() == 0L) {
                byCode.putIfAbsent(t.getCode(), toFormInfo(t));
            }
        }

        List<Map<String, Object>> result = new ArrayList<>(byCode.values());
        // 排序：module_code、code 升序
        result.sort((a, b) -> {
            int c = String.valueOf(a.get("module_code")).compareTo(String.valueOf(b.get("module_code")));
            if (c != 0) {
                return c;
            }
            return String.valueOf(a.get("code")).compareTo(String.valueOf(b.get("code")));
        });

        if (result.size() > 200) {
            log.info("可用表单清单超过 200 条，已截断：tenantId={} total={}", tenantId, result.size());
            result = new ArrayList<>(result.subList(0, 200));
        }
        return result;
    }

    /** 把一行模板收敛成给 agent 的简洁信息（只带四个键）。 */
    private static Map<String, Object> toFormInfo(FormTemplate t) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("code", t.getCode());
        m.put("name", t.getName());
        m.put("module_code", t.getModuleCode());
        m.put("biz_type", t.getBizType());
        return m;
    }

    /**
     * 管理端首页「发起流程」弹层可用的表单（任意登录用户可见，无需 form:manage）。
     *
     * <p>口径：{@code status=ACTIVE} 且 {@code tenant_id IN (tenantId, 0)}（本租户优先，平台默认回退）；
     * 可选 {@code policy} 过滤（{@code submit_policy LIKE %policy%}，如 APPROVAL 命中
     * APPROVAL / APPROVAL+RESUME）。返回轻量字段：code / name / module_code / biz_type /
     * submit_policy（form_template 无独立 description 列，故不含该键）。按 code 去重，上限 200。</p>
     */
    public List<Map<String, Object>> listLaunchable(Long tenantId, String policy) {
        LambdaQueryWrapper<FormTemplate> w = new LambdaQueryWrapper<FormTemplate>()
                .eq(FormTemplate::getStatus, FormTemplate.STATUS_ACTIVE)
                .in(FormTemplate::getTenantId, tenantId, 0L);
        if (policy != null && !policy.isBlank()) {
            w.like(FormTemplate::getSubmitPolicy, policy);
        }
        List<FormTemplate> rows = templateMapper.selectList(w);

        // 本租户行优先于平台默认：先放本租户，再放 tenant_id=0，putIfAbsent 保证留的是本租户行
        Map<String, Map<String, Object>> byCode = new LinkedHashMap<>();
        for (FormTemplate t : rows) {
            if (t.getTenantId() != null && t.getTenantId().equals(tenantId)) {
                byCode.putIfAbsent(t.getCode(), toFormInfoFull(t));
            }
        }
        for (FormTemplate t : rows) {
            if (t.getTenantId() == null || t.getTenantId() == 0L) {
                byCode.putIfAbsent(t.getCode(), toFormInfoFull(t));
            }
        }

        List<Map<String, Object>> result = new ArrayList<>(byCode.values());
        result.sort((a, b) -> {
            int c = String.valueOf(a.get("module_code")).compareTo(String.valueOf(b.get("module_code")));
            if (c != 0) {
                return c;
            }
            return String.valueOf(a.get("code")).compareTo(String.valueOf(b.get("code")));
        });
        if (result.size() > 200) {
            log.info("可发起表单清单超过 200 条，已截断：tenantId={} total={}", tenantId, result.size());
            result = new ArrayList<>(result.subList(0, 200));
        }
        return result;
    }

    /** 把一行模板收敛成「发起流程」弹层信息（含 submit_policy）。 */
    private static Map<String, Object> toFormInfoFull(FormTemplate t) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("code", t.getCode());
        m.put("name", t.getName());
        m.put("module_code", t.getModuleCode());
        m.put("biz_type", t.getBizType());
        m.put("submit_policy", t.getSubmitPolicy());
        return m;
    }

    /**
     * 渲染表单定义（把 schema 转成 fields[]，并把 x-options-ref 由后端解析内联为 options）。
     *
     * <p>不认识的 ref 直接报错（而不是返回空 options），避免前端拿到空下拉还以为正常。</p>
     *
     * @param resolveTenantId 用于解析动态选项（如 leave_types）的租户——动态字典是租户级的
     */
    public FormRender resolveForRender(Long resolveTenantId, String code) {
        FormTemplate t = getByCode(resolveTenantId, code);
        if (t == null) {
            throw BizException.notFound("表单不存在或未启用：" + code);
        }
        Map<String, Object> schema = parseSchema(t.getSchemaJson());
        Object propsObj = schema.get("properties");
        if (!(propsObj instanceof Map)) {
            throw BizException.badRequest("表单字段定义(properties)不能为空");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> props = (Map<String, Object>) propsObj;
        Set<String> required = new java.util.HashSet<>();
        Object reqObj = schema.get("required");
        if (reqObj instanceof List<?>) {
            for (Object o : (List<?>) reqObj) {
                if (o != null) {
                    required.add(o.toString());
                }
            }
        }
        List<FormField> fields = new ArrayList<>();
        for (Map.Entry<String, Object> e : props.entrySet()) {
            String name = e.getKey();
            if (!(e.getValue() instanceof Map)) {
                throw BizException.badRequest("字段「" + name + "」的定义格式错误");
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> def = (Map<String, Object>) e.getValue();
            boolean isRequired = required.contains(name) || Boolean.TRUE.equals(def.get("required"));
            // 控件类型/标签/占位三者的判定统一走 FormFieldMeta（唯一判定点）：
            // 种子与设计器写的是 x-type + title + description，纯标准 schema 也能回退解析。
            fields.add(new FormField(
                    name,
                    cn.aios.resource.support.FormFieldMeta.label(def, name),
                    cn.aios.resource.support.FormFieldMeta.controlType(def),
                    isRequired,
                    resolveOptions(resolveTenantId, def),
                    cn.aios.resource.support.FormFieldMeta.placeholder(def),
                    buildValidation(def),
                    def.get("default")));
        }
        return new FormRender(t.getId(), t.getCode(), t.getName(), t.getVersion(),
                t.getModuleCode(), t.getSubmitPolicy(), fields);
    }

    /** 解析字段选项：x-options-ref 动态引用（目前只支持 leave_types）或静态 enum+enumNames。 */
    private List<Map<String, Object>> resolveOptions(Long tenantId, Map<String, Object> def) {
        Object ref = def.get("x-options-ref");
        if (ref instanceof String r) {
            if ("leave_types".equals(r)) {
                List<LeaveType> types = leaveService.listTypes(tenantId);
                List<Map<String, Object>> opts = new ArrayList<>();
                for (LeaveType lt : types) {
                    Map<String, Object> o = new LinkedHashMap<>();
                    o.put("value", lt.getCode());
                    o.put("label", lt.getName());
                    opts.add(o);
                }
                return opts;
            }
            throw BizException.badRequest("不支持的选项引用（x-options-ref）：" + r);
        }
        Object en = def.get("enum");
        if (en instanceof List<?> list) {
            List<?> names = def.get("enumNames") instanceof List<?> n ? n : null;
            List<Map<String, Object>> opts = new ArrayList<>();
            for (int i = 0; i < list.size(); i++) {
                Object v = list.get(i);
                Object l = (names != null && i < names.size()) ? names.get(i) : v;
                Map<String, Object> o = new LinkedHashMap<>();
                o.put("value", v);
                o.put("label", l);
                opts.add(o);
            }
            return opts;
        }
        return null;
    }

    /** 把 schema 里的约束收敛成一个 validation 小对象（minimum/maximum/maxLength/pattern）。 */
    private Map<String, Object> buildValidation(Map<String, Object> def) {
        Map<String, Object> v = new LinkedHashMap<>();
        if (def.containsKey("minimum")) {
            v.put("minimum", def.get("minimum"));
        }
        if (def.containsKey("maximum")) {
            v.put("maximum", def.get("maximum"));
        }
        if (def.containsKey("maxLength")) {
            v.put("maxLength", def.get("maxLength"));
        }
        if (def.containsKey("pattern")) {
            v.put("pattern", def.get("pattern"));
        }
        return v.isEmpty() ? null : v;
    }

    /** 新建表单定义（version=1 并写首版快照）。 */
    public FormTemplate create(AuthUser user, FormSave req) {
        validateSave(req);
        FormTemplate t = toEntity(null, req);
        t.setTenantId(user.getTenantId());
        t.setCreatedBy(user.getUserId());
        t.setCreatedAt(LocalDateTime.now());
        t.setStatus(FormTemplate.STATUS_ACTIVE);
        t.setVersion(1);
        templateMapper.insert(t);
        insertVersionSnapshot(t);
        return t;
    }

    /**
     * 更新表单定义：自动 version+1，并把新版本写入 form_template_version 快照，旧版本永不覆盖。
     *
     * @throws BizException.notFound 本租户没有该 code 的活行时
     */
    public FormTemplate update(AuthUser user, String code, FormSave req) {
        validateSave(req);
        FormTemplate old = templateMapper.selectOne(new LambdaQueryWrapper<FormTemplate>()
                .eq(FormTemplate::getTenantId, user.getTenantId())
                .eq(FormTemplate::getCode, code)
                .eq(FormTemplate::getStatus, FormTemplate.STATUS_ACTIVE)
                .last("limit 1"));
        if (old == null) {
            throw BizException.notFound("表单不存在或未启用：" + code);
        }
        int newVersion = old.getVersion() + 1;
        old.setName(req.name());
        old.setModuleCode(req.moduleCode());
        old.setBizType(req.bizType());
        old.setSchemaJson(req.schemaJson());
        old.setLayoutJson(req.layoutJson());
        old.setSubmitPolicy(req.submitPolicy());
        old.setReceiptJson(req.receiptJson());
        old.setVersion(newVersion);
        old.setUpdatedAt(LocalDateTime.now());
        templateMapper.updateById(old);
        insertVersionSnapshot(old);
        return old;
    }

    /** 列表/筛选（moduleCode/status 可选；分页）。 */
    public IPage<FormTemplate> list(Long tenantId, String moduleCode, String status, int page, int size) {
        LambdaQueryWrapper<FormTemplate> w = new LambdaQueryWrapper<FormTemplate>()
                .eq(FormTemplate::getTenantId, tenantId)
                .orderByDesc(FormTemplate::getId);
        if (moduleCode != null && !moduleCode.isBlank()) {
            w.eq(FormTemplate::getModuleCode, moduleCode);
        }
        if (status != null && !status.isBlank()) {
            w.eq(FormTemplate::getStatus, status);
        }
        return templateMapper.selectPage(new Page<>(Math.max(page, 1), Math.max(size, 1)), w);
    }

    /** 写一份版本快照（version 取自实体当前 version）。 */
    private void insertVersionSnapshot(FormTemplate t) {
        FormTemplateVersion v = new FormTemplateVersion();
        v.setTemplateId(t.getId());
        v.setVersion(t.getVersion());
        v.setSchemaJson(t.getSchemaJson());
        v.setLayoutJson(t.getLayoutJson());
        v.setReceiptJson(t.getReceiptJson());
        v.setCreatedBy(t.getCreatedBy());
        v.setCreatedAt(LocalDateTime.now());
        versionMapper.insert(v);
    }

    private FormTemplate toEntity(Long id, FormSave req) {
        FormTemplate t = new FormTemplate();
        t.setId(id);
        t.setCode(req.code());
        t.setName(req.name());
        t.setModuleCode(req.moduleCode());
        t.setBizType(req.bizType());
        t.setSchemaJson(req.schemaJson());
        t.setLayoutJson(req.layoutJson());
        t.setSubmitPolicy(req.submitPolicy() == null || req.submitPolicy().isBlank()
                ? FormTemplate.POLICY_LEDGER : req.submitPolicy());
        t.setReceiptJson(req.receiptJson());
        t.setUpdatedAt(LocalDateTime.now());
        return t;
    }

    private void validateSave(FormSave req) {
        if (req.code() == null || req.code().isBlank()) {
            throw BizException.badRequest("表单码(code)不能为空");
        }
        if (req.name() == null || req.name().isBlank()) {
            throw BizException.badRequest("表单名称(name)不能为空");
        }
        if (req.schemaJson() == null || req.schemaJson().isBlank()) {
            throw BizException.badRequest("表单结构(schema_json)不能为空");
        }
        // 校验 schema 结构合法（至少能解析、properties 非空），避免把坏定义写进库
        Map<String, Object> schema = parseSchema(req.schemaJson());
        Object props = schema.get("properties");
        if (!(props instanceof Map) || ((Map<?, ?>) props).isEmpty()) {
            throw BizException.badRequest("表单结构(schema_json)的 properties 不能为空");
        }
        // 业务规则配置期校验：坏配置写不进库，运行期就不会静默失效
        validateRulesConfig(schema);
    }

    /** `when.op` 白名单（与 FormSchemaValidator 保持一致）。 */
    private static final Set<String> RULE_OPS = Set.of(
            "eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "empty", "not_empty");

    /** `then.action` 白名单（运行期只认这两个）。 */
    private static final Set<String> RULE_ACTIONS = Set.of("block", "require");

    /**
     * 规则配置期校验：schema 含 {@code rules}/{@code x-rules} 时逐条校验结构合法性，
     * 坏配置一律抛出（不让它写进库），运行期 {@code FormSchemaValidator.validateRules} 就不必再抛。
     */
    private void validateRulesConfig(Map<String, Object> schema) {
        Object rulesObj = schema.get("rules");
        if (!(rulesObj instanceof List)) {
            rulesObj = schema.get("x-rules"); // 兼容 x-rules
        }
        if (!(rulesObj instanceof List<?> rules)) {
            return; // 无规则：放行
        }
        int idx = 0;
        for (Object ro : rules) {
            idx++;
            if (!(ro instanceof Map<?, ?> rm)) {
                throw BizException.badRequest("表单规则配置错误：第 " + idx + " 条必须是对象");
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> rule = (Map<String, Object>) rm;
            Object whenObj = rule.get("when");
            if (!(whenObj instanceof Map<?, ?> wm)) {
                throw BizException.badRequest("表单规则配置错误：第 " + idx + " 条缺少 when 条件");
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> when = (Map<String, Object>) wm;
            Object field = when.get("field");
            if (!(field instanceof String fs) || fs.isBlank()) {
                throw BizException.badRequest("表单规则配置错误：第 " + idx + " 条 when.field 不能为空");
            }
            Object op = when.get("op");
            if (!(op instanceof String os) || !RULE_OPS.contains(os)) {
                throw BizException.badRequest("表单规则配置错误：第 " + idx + " 条 when.op 非法（" + op + "）");
            }
            Object thenObj = rule.get("then");
            if (!(thenObj instanceof Map<?, ?> tm)) {
                throw BizException.badRequest("表单规则配置错误：第 " + idx + " 条缺少 then 动作");
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> then = (Map<String, Object>) tm;
            Object action = then.get("action");
            if (!(action instanceof String as) || !RULE_ACTIONS.contains(as)) {
                throw BizException.badRequest("表单规则配置错误：第 " + idx
                        + " 条 then.action 必须是 block 或 require（" + action + "）");
            }
        }
    }

    private Map<String, Object> parseSchema(String schemaJson) {
        try {
            return objectMapper.readValue(schemaJson,
                    new TypeReference<LinkedHashMap<String, Object>>() {
                    });
        } catch (Exception e) {
            throw BizException.badRequest("表单结构(schema_json)不是合法的 JSON");
        }
    }
}
