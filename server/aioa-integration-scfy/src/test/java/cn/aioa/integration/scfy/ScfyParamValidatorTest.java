package cn.aioa.integration.scfy;

import cn.aioa.integration.scfy.contract.ScfyCatalog;
import cn.aioa.integration.scfy.validate.ScfyParamValidator;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 校验器行为测试。
 *
 * <p>重点不是「能不能校验必填」，而是<b>能不能拦住三类会静默出错的调用</b>：
 * 照文档写错的参数名（shopId）、返回空集的参数值（市州全称）、
 * 传了等于没传的条件（level≠country）。这三类如果放过，错误会伪装成业务结论。</p>
 */
class ScfyParamValidatorTest {

    private final ScfyParamValidator v = new ScfyParamValidator();

    @Test
    @DisplayName("照文档传 shopId 会被拦下，并指出正确参数名")
    void rejectsDocParamName() {
        Map<String, Object> in = new HashMap<>();
        in.put("cityName", "成都市");
        in.put("shopId", "140");     // 文档写的是 shopId，实测要 id

        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("shop_detail"), in);

        assertFalse(r.ok(), "错误的参数名必须被拒绝 —— 放行会变成「参数没生效」");
        assertTrue(String.join(" ", r.errors()).contains("shopId"), "错误信息应指出是 shopId 有问题");
        assertTrue(String.join(" ", r.errors()).contains("id"), "错误信息应给出正确参数名 id");
    }

    @Test
    @DisplayName("市州用全称会被拦下（实测全称返回 0 条，属静默空结果）")
    void rejectsFullCityName() {
        Map<String, Object> in = new HashMap<>();
        in.put("area", "甘孜藏族自治州");   // 文档示例；实测 0 条

        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("inheritor_list_by_area"), in);

        assertFalse(r.ok(), "全称必须被拦下，否则返回空集会被当成「当地没有传承人」");
        assertTrue(String.join(" ", r.errors()).contains("甘孜藏族自治州"));
    }

    @Test
    @DisplayName("市州简称放行")
    void acceptsShortCityName() {
        Map<String, Object> in = new HashMap<>();
        in.put("area", "甘孜州");

        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("inheritor_list_by_area"), in);

        assertTrue(r.ok(), "简称应放行：" + r.errors());
        assertEquals("甘孜州", r.normalized().get("area"));
    }

    @Test
    @DisplayName("必填缺失时给出可读追问，而不是空错误")
    void asksUserWhenRequiredMissing() {
        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("project_count_by_area"), Map.of());

        assertFalse(r.ok());
        assertNotNull(r.askUser(), "缺必填时必须生成追问话术");
        assertTrue(r.askUser().contains("市州") || r.askUser().contains("area"),
                "追问要说明缺的是什么，而不是只报参数名");
        assertTrue(r.askUser().contains("成都市") || r.askUser().contains("请补充"),
                "追问应给出示例或明确的下一步");
    }

    @Test
    @DisplayName("pageSize 越界被拦下")
    void rejectsOutOfRangePageSize() {
        Map<String, Object> in = new HashMap<>();
        in.put("area", "成都市");
        in.put("pageSize", "9999");

        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("inheritor_list_by_area"), in);

        assertFalse(r.ok());
        assertTrue(String.join(" ", r.errors()).contains("pageSize"));
    }

    @Test
    @DisplayName("level=un 放行但必须给出「不生效」预警")
    void warnsOnIneffectiveLevel() {
        Map<String, Object> in = new HashMap<>();
        in.put("level", "un");

        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("project_type_data"), in);

        assertTrue(r.ok(), "un 是合法枚举值（用户已确认含联合国级），不应拒绝：" + r.errors());
        assertFalse(r.warnings().isEmpty(), "但必须预警：实测该值不会生效");
        assertTrue(String.join(" ", r.warnings()).contains("不会生效"));
    }

    @Test
    @DisplayName("正常参数归一化：数字型参数被转成整数")
    void normalizesNumericParams() {
        Map<String, Object> in = new HashMap<>();
        in.put("area", "成都市");
        in.put("pageNum", "2");
        in.put("pageSize", "20");

        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("inheritor_list_by_area"), in);

        assertTrue(r.ok(), r.errors().toString());
        assertEquals(2, r.normalized().get("pageNum"));
        assertEquals(20, r.normalized().get("pageSize"));
        assertEquals("成都市", r.normalized().get("area"));
    }

    @Test
    @DisplayName("空白字符串视为未传，不拼进 URL")
    void blankIsTreatedAsAbsent() {
        Map<String, Object> in = new HashMap<>();
        in.put("area", "   ");     // 空白即「未传」（area 在该接口可选）
        in.put("pageNum", "");     // 空串同样视为未传

        ScfyParamValidator.Result r = v.validate(ScfyCatalog.byId("inheritor_list_by_area"), in);

        assertTrue(r.ok(), r.errors().toString());
        assertTrue(r.normalized().isEmpty(), "空白值不应进入归一化结果");
    }
}
