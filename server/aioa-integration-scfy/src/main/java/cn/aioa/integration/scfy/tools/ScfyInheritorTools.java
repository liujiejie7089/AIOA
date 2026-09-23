package cn.aioa.integration.scfy.tools;

import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 传承人域工具（9 个，全部只读，全部来自免登录的 {@code /show/inheritor/*}）。
 *
 * <p><b>工具描述里为什么反复写「市州必须用简称」</b>：这不是啰嗦。模型填参数的唯一依据
 * 就是 description —— 而接口文档在这一处是错的（文档示例「甘孜藏族自治州」实测返回 0 条）。
 * 描述里不写，模型就会照文档传全称，得到空列表，然后告诉用户「甘孜州没有传承人」。
 * <b>一个错误的参数值会伪装成一个业务结论</b>，所以警示必须出现在模型能读到的地方。</p>
 */
@Component
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyInheritorTools {

    private final ScfyToolSupport support;

    public ScfyInheritorTools(ScfyToolSupport support) {
        this.support = support;
    }

    @AioaTool(code = "scfy_inheritor_list_by_area",
            name = "非遗传承人-按市州查询列表",
            description = "查询四川省某市州的非遗传承人名单，回答「某地有哪些传承人」「某市州传承人有多少」。"
                    + "市州必须用简称（成都市 / 甘孜州 / 凉山州），用全称（甘孜藏族自治州）会返回空列表且不报错；"
                    + "不传市州表示全省。返回 dataList（含 id 与 name，id 可用于查详情）与 totalCount。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> listByArea(
            @AioaToolParam(name = "area", description = "市州简称，如 成都市 / 甘孜州；不传表示全省", required = false)
            String area,
            @AioaToolParam(name = "level", description = "等级筛选。实测只有 country（国家级）生效，un/province/city/county 会被忽略",
                    required = false) String level,
            @AioaToolParam(name = "pageNum", description = "页码，缺省 1", required = false, type = "integer")
            Integer pageNum,
            @AioaToolParam(name = "pageSize", description = "每页条数，缺省 10，上限 100", required = false, type = "integer")
            Integer pageSize) {
        return support.call("inheritor_list_by_area",
                ScfyArgs.of("area", area, "level", level, "pageNum", pageNum, "pageSize", pageSize));
    }

    @AioaTool(code = "scfy_inheritor_detail",
            name = "非遗传承人-详情",
            description = "查询单个非遗传承人的详情（姓名、级别、性别、出生、门类、简介、所属单位、视频地址）。"
                    + "id 必须先由 scfy_inheritor_list_by_area 获取 —— 它是形如 UUID_级别后缀 的字符串，不是纯数字，不要臆造。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> detail(
            @AioaToolParam(name = "id", description = "传承人 id，取自 scfy_inheritor_list_by_area 返回的 dataList[].id",
                    required = true) String id) {
        return support.call("inheritor_detail", ScfyArgs.of("id", id));
    }

    @AioaTool(code = "scfy_inheritor_type_data",
            name = "非遗传承人-门类分布",
            description = "查询非遗传承人按项目门类（传统技艺 / 传统戏剧 / 民俗 等十大类）的数量分布，"
                    + "回答「哪些门类的传承人多」。返回 data 数组与 projectTypeMap。"
                    + "注意：实测本接口返回的是项目门类分布，不是等级分布（接口文档在此描述有误）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> typeData(
            @AioaToolParam(name = "level", description = "等级，必填。实测只有 country（国家级）生效", required = true)
            String level) {
        return support.call("inheritor_type_data", ScfyArgs.of("level", level));
    }

    @AioaTool(code = "scfy_inheritor_gender_data",
            name = "非遗传承人-性别比例",
            description = "查询非遗传承人的男女性别数量，回答「男女比例」「女性传承人有多少」。"
                    + "返回 manCount / womanCount / totalCount（注意字段名不是文档写的 male/female）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> genderData(
            @AioaToolParam(name = "level", description = "等级，必填。实测只有 country（国家级）生效", required = true)
            String level) {
        return support.call("inheritor_gender_data", ScfyArgs.of("level", level));
    }

    @AioaTool(code = "scfy_inheritor_birthday_data",
            name = "非遗传承人-出生年代分布",
            description = "查询非遗传承人的出生年代分布，回答「传承人年龄结构」「哪个年代的传承人多」。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> birthdayData(
            @AioaToolParam(name = "level", description = "等级，必填。实测只有 country（国家级）生效", required = true)
            String level) {
        return support.call("inheritor_birthday_data", ScfyArgs.of("level", level));
    }

    @AioaTool(code = "scfy_inheritor_education_data",
            name = "非遗传承人-学历分布",
            description = "查询非遗传承人的学历（文化程度）分布，按国家级与省级两组返回。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> educationData(
            @AioaToolParam(name = "level", description = "等级，必填。实测只有 country（国家级）生效", required = true)
            String level) {
        return support.call("inheritor_education_data", ScfyArgs.of("level", level));
    }

    @AioaTool(code = "scfy_inheritor_count_by_area",
            name = "非遗传承人-各市州数量对比",
            description = "查询全省 21 个市州的传承人数量对比，回答「哪个市州的传承人最多」。"
                    + "返回每个市州的五档计数（country_inheritor / province_inheritor / city_inheritor / "
                    + "county_inheritor / all）与 short_name。这是获取合法市州名称的可靠来源。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> countByArea(
            @AioaToolParam(name = "name", description = "通常无需传；固定「四川省」表示全省汇总", required = false)
            String name) {
        return support.call("inheritor_count_by_area", ScfyArgs.of("name", name));
    }

    @AioaTool(code = "scfy_inheritor_yhwd_data",
            name = "非遗传承人-云上非遗分布",
            description = "查询「云上非遗」口径下各市州的传承人分布（含联合国级到县级五档）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> yhwdData() {
        return support.call("inheritor_yhwd_data", Map.of());
    }

    @AioaTool(code = "scfy_inheritor_video",
            name = "非遗传承人-视频地址",
            description = "查询传承人的视频播放地址。返回 exist 与 viewUrl —— exist=false 表示该传承人暂无视频，"
                    + "这是正常结果而非错误，不要重试。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> video(
            @AioaToolParam(name = "inheritorId", description = "传承人 id，取自 scfy_inheritor_list_by_area",
                    required = true) String inheritorId) {
        return support.call("inheritor_video", ScfyArgs.of("inheritorId", inheritorId));
    }
}
