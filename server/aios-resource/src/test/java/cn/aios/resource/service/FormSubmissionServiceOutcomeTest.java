package cn.aios.resource.service;

import cn.aios.org.service.ApprovalFlowService;
import cn.aios.resource.entity.FormSubmission;
import cn.aios.resource.mapper.FormSubmissionMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * FormSubmissionService 审批终态回写单测（docs/52 P4 铁律 2，纯单测、不起 Spring）。
 *
 * <p>锁死四类行为：
 * <ol>
 *   <li>REJECTED 决策 → mapper 收到 status=REJECTED 的更新；</li>
 *   <li>APPROVED 决策 → mapper 收到 status=APPROVED 的更新；</li>
 *   <li>查不到 submission → 不抛异常（证明不是靠 NPE 静默）；</li>
 *   <li>已是终态 → 不再更新（幂等，断言 update 调用次数为 0）。</li>
 * </ol>
 *
 * <p>说明：{@code onApprovalFinished} 直接改写 {@code selectOne} 返回的同一对象并调用
 * {@code updateById(sub)}，故断言复用该对象即可，无需 {@code ArgumentCaptor}（也避开
 * MyBatis-Plus {@code updateById(T)} 与 {@code updateById(Collection<T>)} 重载歧义）。</p>
 */
class FormSubmissionServiceOutcomeTest {

    private final FormTemplateService templateService = mock(FormTemplateService.class);
    private final FormSubmissionMapper submissionMapper = mock(FormSubmissionMapper.class);
    private final ApprovalFlowService approvalFlowService = mock(ApprovalFlowService.class);

    private final FormSubmissionService service =
            new FormSubmissionService(templateService, submissionMapper, approvalFlowService);

    private static FormSubmission approving(Long id, Long orderId) {
        FormSubmission s = new FormSubmission();
        s.setId(id);
        s.setApprovalOrderId(orderId);
        s.setStatus(FormSubmission.STATUS_APPROVING);
        return s;
    }

    @Test
    @DisplayName("REJECTED 决策 → submission 被改写为 REJECTED")
    void rejectedWritesRejected() {
        Long orderId = 100L;
        FormSubmission sub = approving(1L, orderId);
        when(submissionMapper.selectOne(any())).thenReturn(sub);

        service.onApprovalFinished(orderId, "REJECTED");

        assertEquals(FormSubmission.STATUS_REJECTED, sub.getStatus());
        verify(submissionMapper, times(1)).updateById(sub);
    }

    @Test
    @DisplayName("APPROVED 决策 → submission 被改写为 APPROVED")
    void approvedWritesApproved() {
        Long orderId = 200L;
        FormSubmission sub = approving(2L, orderId);
        when(submissionMapper.selectOne(any())).thenReturn(sub);

        service.onApprovalFinished(orderId, "APPROVED");

        assertEquals(FormSubmission.STATUS_APPROVED, sub.getStatus());
        verify(submissionMapper, times(1)).updateById(sub);
    }

    @Test
    @DisplayName("查不到 submission → 不抛异常（证明不是靠 NPE 静默）")
    void noSubmissionDoesNotThrow() {
        Long orderId = 300L;
        when(submissionMapper.selectOne(any())).thenReturn(null);

        assertDoesNotThrow(() -> service.onApprovalFinished(orderId, "APPROVED"));
        verify(submissionMapper, never()).updateById(any(FormSubmission.class));
    }

    @Test
    @DisplayName("已是终态 → 不再更新（幂等，断言 update 调用次数）")
    void alreadyTerminalIsIdempotent() {
        Long orderId = 400L;
        FormSubmission sub = new FormSubmission();
        sub.setId(3L);
        sub.setApprovalOrderId(orderId);
        sub.setStatus(FormSubmission.STATUS_APPROVED); // 已是终态
        when(submissionMapper.selectOne(any())).thenReturn(sub);

        service.onApprovalFinished(orderId, "APPROVED");

        verify(submissionMapper, never()).updateById(any(FormSubmission.class));
    }
}
