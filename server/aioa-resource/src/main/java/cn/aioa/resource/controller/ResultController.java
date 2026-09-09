package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.UserResult;
import cn.aioa.resource.mapper.UserResultMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 成果沉淀（V1.2 新增）：会话产出「存为成果」后可继续编辑 / 发起审批 / 转发。
 *   GET  /api/v1/results          —— 我的成果列表（不含正文，避免大字段传输）
 *   POST /api/v1/results          —— 存为成果
 *   GET  /api/v1/results/{id}     —— 成果详情（含正文）
 *   PUT  /api/v1/results/{id}     —— 编辑正文 / 提交审批（status=SUBMITTED）
 */
@RestController
@RequestMapping("/api/v1/results")
@RequiredArgsConstructor
public class ResultController {

    private final UserResultMapper resultMapper;

    /** 列表项：不带正文 */
    public record ResultItemView(Long id, String title, String icon, String meta, String status, String createdAt) {

        static ResultItemView from(UserResult r) {
            return new ResultItemView(r.getId(), r.getTitle(), r.getIcon(), r.getMeta(), r.getStatus(),
                    r.getCreatedAt() == null ? null : r.getCreatedAt().toString());
        }
    }

    /** 详情：含正文 */
    public record ResultDetailView(Long id, String title, String icon, String meta, String body,
                                   String status, String createdAt) {

        static ResultDetailView from(UserResult r) {
            return new ResultDetailView(r.getId(), r.getTitle(), r.getIcon(), r.getMeta(), r.getBody(),
                    r.getStatus(), r.getCreatedAt() == null ? null : r.getCreatedAt().toString());
        }
    }

    @GetMapping
    public ApiResponse<List<ResultItemView>> list() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(resultMapper.selectList(new LambdaQueryWrapper<UserResult>()
                        .eq(UserResult::getTenantId, user.getTenantId())
                        .eq(UserResult::getUserId, user.getUserId())
                        .orderByDesc(UserResult::getId))
                .stream().map(ResultItemView::from).toList());
    }

    @GetMapping("/{id}")
    public ApiResponse<ResultDetailView> detail(@PathVariable Long id) {
        AuthUser user = AuthUserContext.require();
        UserResult r = resultMapper.selectById(id);
        if (r == null || !user.getTenantId().equals(r.getTenantId())) {
            throw BizException.notFound("成果不存在：" + id);
        }
        return ApiResponse.ok(ResultDetailView.from(r));
    }

    @PostMapping
    public ApiResponse<ResultItemView> create(@RequestBody UserResult body) {
        AuthUser user = AuthUserContext.require();
        String title = body.getTitle() == null ? "" : body.getTitle().trim();
        if (title.isEmpty()) {
            throw BizException.badRequest("成果标题不能为空");
        }
        UserResult r = new UserResult();
        r.setTenantId(user.getTenantId());
        r.setUserId(user.getUserId());
        r.setTitle(title);
        r.setIcon(body.getIcon() == null || body.getIcon().isBlank() ? "doc" : body.getIcon());
        r.setMeta(body.getMeta());
        r.setBody(body.getBody());
        r.setStatus(body.getStatus() == null ? UserResult.STATUS_DRAFT : body.getStatus());
        r.setCreatedAt(LocalDateTime.now());
        r.setUpdatedAt(LocalDateTime.now());
        r.setCreatedBy(user.getUserId());
        resultMapper.insert(r);
        return ApiResponse.ok(ResultItemView.from(r));
    }

    @PutMapping("/{id}")
    public ApiResponse<ResultDetailView> update(@PathVariable Long id, @RequestBody UserResult body) {
        AuthUser user = AuthUserContext.require();
        UserResult cur = resultMapper.selectById(id);
        if (cur == null || !user.getTenantId().equals(cur.getTenantId())
                || !user.getUserId().equals(cur.getUserId())) {
            throw BizException.notFound("成果不存在或非本人成果：" + id);
        }
        if (body.getTitle() != null && !body.getTitle().isBlank()) cur.setTitle(body.getTitle().trim());
        if (body.getBody() != null) cur.setBody(body.getBody());
        if (body.getMeta() != null) cur.setMeta(body.getMeta());
        if (body.getIcon() != null && !body.getIcon().isBlank()) cur.setIcon(body.getIcon());
        if (body.getStatus() != null) cur.setStatus(body.getStatus());
        cur.setUpdatedAt(LocalDateTime.now());
        resultMapper.updateById(cur);
        return ApiResponse.ok(ResultDetailView.from(cur));
    }
}
