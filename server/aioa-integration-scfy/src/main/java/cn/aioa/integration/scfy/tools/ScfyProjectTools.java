package cn.aioa.integration.scfy.tools;

import cn.aioa.tool.sdk.AioaTool;
import cn.aioa.tool.sdk.AioaToolParam;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 非遗项目域工具（8 个，只读，来自免登录的 {@code /show/project/*}）。
 *
 * <p>本域的坑集中在 {@code level} 参数：接口文档把它列为筛选条件，但实测
 * {@code /show/project/getProjectListByArea} 会<b>完全忽略</b>它（传 country 与不传同为 1411 条），
 * 而 {@code getProjectTypeData} 又把它列为必填且只有 country 生效。
 * 因此「按等级筛选项目」这件事，正确入口是 {@code scfy_project_count_by_area}
 * （按市州返回各等级数量），而不是给列表接口加 level。</p>
 */
@Component
@ConditionalOnProperty(prefix = "aioa.integration.scfy", name = "enabled", havingValue = "true")
public class ScfyProjectTools {

    private final ScfyToolSupport support;

    public ScfyProjectTools(ScfyToolSupport support) {
        this.support = support;
    }

    @AioaTool(code = "scfy_project_list_by_area",
            name = "非遗项目-查询列表",
            description = "查询四川省非遗项目列表，回答「有哪些非遗项目」「某地有哪些非遗项目」。"
                    + "市州必须用简称（甘孜州 / 凉山州），不传表示全省（约 1411 条）。"
                    + "注意 level 参数实测被本接口忽略，按等级查数量请改用 scfy_project_count_by_area。"
                    + "返回 dataList（含 project_base_id，可用于查详情）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> listByArea(
            @AioaToolParam(name = "area", description = "市州简称；不传表示全省", required = false) String area,
            @AioaToolParam(name = "level", description = "等级。实测本接口忽略该参数，传了等于没传", required = false)
            String level,
            @AioaToolParam(name = "pageNum", description = "页码，缺省 1", required = false, type = "integer")
            Integer pageNum,
            @AioaToolParam(name = "pageSize", description = "每页条数，缺省 10，上限 100", required = false, type = "integer")
            Integer pageSize) {
        return support.call("project_list_by_area",
                ScfyArgs.of("area", area, "level", level, "pageNum", pageNum, "pageSize", pageSize));
    }

    @AioaTool(code = "scfy_project_detail",
            name = "非遗项目-详情",
            description = "查询单个非遗项目的详情（项目名、级别、保护单位、传承谱系、简介）。"
                    + "id 必须来自 scfy_project_list_by_area 的 project_base_id，形如 2-UN-1 / 2-GJ-92，不要臆造。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> detail(
            @AioaToolParam(name = "id", description = "项目 id（project_base_id），取自 scfy_project_list_by_area",
                    required = true) String id) {
        return support.call("project_detail", ScfyArgs.of("id", id));
    }

    @AioaTool(code = "scfy_project_type_data",
            name = "非遗项目-门类分布",
            description = "查询非遗项目按十大类（传统技艺 / 传统戏剧 / 传统音乐 等）的数量分布。"
                    + "level 为必填，但实测只有 country 生效，其余取值会返回未过滤结果。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> typeData(
            @AioaToolParam(name = "level", description = "等级，必填。实测只有 country 生效", required = true)
            String level) {
        return support.call("project_type_data", ScfyArgs.of("level", level));
    }

    @AioaTool(code = "scfy_project_batch_data",
            name = "非遗项目-批次分布",
            description = "查询非遗项目按批次的分布，返回国家级/省级 × 折线/柱状四组数据。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> batchData(
            @AioaToolParam(name = "area", description = "市州简称；不传表示全省", required = false) String area) {
        return support.call("project_batch_data", ScfyArgs.of("area", area));
    }

    @AioaTool(code = "scfy_project_count_by_area",
            name = "非遗项目-各等级数量",
            description = "查询指定市州各等级的非遗项目数量 —— 这是查看「联合国级」等档位数量的正确入口"
                    + "（返回 level_name 与 num，如 联合国教科文组织=1 / 国家级=26 / 省级=119）。"
                    + "要统计等级分布时用它，不要给列表接口传 level。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> countByArea(
            @AioaToolParam(name = "area", description = "市州简称，如 成都市 / 甘孜州", required = true)
            String area) {
        return support.call("project_count_by_area", ScfyArgs.of("area", area));
    }

    @AioaTool(code = "scfy_project_area_summary",
            name = "非遗项目-各市州汇总",
            description = "查询全省各市州非遗项目数量汇总，返回每个市州的六档计数"
                    + "（un_project 联合国级 / country_project / province_project / city_project / "
                    + "county_project / all），回答「哪个市州非遗项目最多」。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> areaSummary(
            @AioaToolParam(name = "name", description = "通常无需传；固定「四川省」表示全省汇总", required = false)
            String name) {
        return support.call("project_area_summary", ScfyArgs.of("name", name));
    }

    @AioaTool(code = "scfy_project_yhwd_data",
            name = "非遗项目-云上非遗分布",
            description = "查询「云上非遗」口径下各市州的项目分布（六档：联合国 / 国家 / 省 / 市 / 县 / 区）。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> yhwdData() {
        return support.call("project_yhwd_data", Map.of());
    }

    @AioaTool(code = "scfy_project_video",
            name = "非遗项目-视频地址",
            description = "查询非遗项目的视频播放地址。exist=false 表示暂无视频，是正常结果而非错误。",
            domain = "scfy", riskLevel = "LOW", owner = "integration")
    public Map<String, Object> video(
            @AioaToolParam(name = "projectBaseId", description = "项目 id（project_base_id）", required = true)
            String projectBaseId) {
        return support.call("project_video", ScfyArgs.of("projectBaseId", projectBaseId));
    }
}
