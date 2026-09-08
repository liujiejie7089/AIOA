package cn.aioa.resource.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.AiExpert;
import cn.aioa.resource.entity.AiSkill;
import cn.aioa.resource.service.CatalogService;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 用户端目录：专家 / 技能。
 * 返回结构与交互原型一致（key / name / icon / desc / tags / intro / recs）。
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class CatalogController {

    private final CatalogService catalogService;

    public record ExpertView(String key, String name, String icon, String desc,
                             List<Object> tags, String intro, List<Object> recs) {

        static ExpertView from(AiExpert e) {
            return new ExpertView(e.getExpertKey(), e.getName(), e.getIcon(), e.getSummary(),
                    e.getTags(), e.getIntro(), e.getRecs());
        }
    }

    public record SkillView(String name, String icon, Integer est, List<Object> fields, String expertKey) {

        static SkillView from(AiSkill s) {
            return new SkillView(s.getSkillName(), s.getIcon(), s.getEstTokens(), s.getFields(), s.getExpertKey());
        }
    }

    @GetMapping("/experts")
    public ApiResponse<List<ExpertView>> experts() {
        return ApiResponse.ok(catalogService.experts(AuthUserContext.tenantIdOrDefault())
                .stream().map(ExpertView::from).toList());
    }

    @GetMapping("/skills")
    public ApiResponse<List<SkillView>> skills() {
        return ApiResponse.ok(catalogService.skills(AuthUserContext.tenantIdOrDefault())
                .stream().map(SkillView::from).toList());
    }
}
