-- V11: 审批单关联业务成果（result_id），支持审批通过/驳回后回写成果状态
ALTER TABLE approval_order
    ADD COLUMN result_id BIGINT NULL COMMENT '关联成果ID（bizType=RESULT 时回写状态用）' AFTER conversation_id;
