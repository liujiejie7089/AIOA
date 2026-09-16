-- V38 回填历史授权单的「处理方留痕」（需求④：审核记录必须能回答「谁处理的」）
--
-- 背景：granted_by / granted_at 在语义上是「终态处理人 / 处理时间」（通过 = 发放人，驳回 = 驳回人），
--   V36 建表时只定义了列，终态回调只写 ACTIVE 分支，REJECTED 分支早期版本没写这两列，
--   于是出现「状态已是 REJECTED、却没有处理人」的记录，审核记录中心展示为空。
--   这不是数据本身缺失 —— 处理人一直完好地存在 approval_task 里（REJECTED 节点带 approver_id /
--   decided_at / note），只是当时没复制过来。
--
-- 因此本迁移做纯数据修复：从关联单据的「最后一个已决节点」反查，补齐终态行的处理方三要素。
--   取「seq 最大的已决节点」而非「最后一个 APPROVED」：驳回场景下 seq=1 是 REJECTED、
--   其后节点是 SKIPPED（decided_at 为空），只有把 REJECTED 纳入候选才能取到真正的驳回人。
--   一并回填 audit_note（驳回意见），语义与 PermissionGrantService.onRejected 保持一致。
--
-- 幂等：三重 WHERE 限定（终态 + 处理人为空 + 有单据），重复执行不会覆盖已正确的行；
--   全新库无此类行，迁移为空操作。
-- 只读约束：仅 UPDATE permission_grant，不触碰 approval_task / approval_order（审计链不回写）。

-- ---------- 补齐处理人（终态行的 granted_by 为空时，从最后一个已决节点取） ----------
UPDATE permission_grant g
SET g.granted_by = (
        SELECT t.approver_id
        FROM approval_task t
        WHERE t.order_id = g.order_id
          AND t.status IN ('APPROVED', 'REJECTED')
          AND t.approver_id IS NOT NULL
        ORDER BY t.seq DESC
        LIMIT 1
    )
WHERE g.status IN ('ACTIVE', 'REJECTED')
  AND g.granted_by IS NULL
  AND g.order_id IS NOT NULL
  AND EXISTS (
        SELECT 1
        FROM approval_task t
        WHERE t.order_id = g.order_id
          AND t.status IN ('APPROVED', 'REJECTED')
          AND t.approver_id IS NOT NULL
    );

-- ---------- 补齐处理时间（同上节点口径；仅在原值为空时写入） ----------
UPDATE permission_grant g
SET g.granted_at = (
        SELECT t.decided_at
        FROM approval_task t
        WHERE t.order_id = g.order_id
          AND t.status IN ('APPROVED', 'REJECTED')
          AND t.decided_at IS NOT NULL
        ORDER BY t.seq DESC
        LIMIT 1
    )
WHERE g.status IN ('ACTIVE', 'REJECTED')
  AND g.granted_at IS NULL
  AND g.order_id IS NOT NULL
  AND EXISTS (
        SELECT 1
        FROM approval_task t
        WHERE t.order_id = g.order_id
          AND t.status IN ('APPROVED', 'REJECTED')
          AND t.decided_at IS NOT NULL
    );

-- ---------- 补齐驳回意见（仅驳回态、仅原值为空、只认 REJECTED 节点） ----------
UPDATE permission_grant g
SET g.audit_note = (
        SELECT t.note
        FROM approval_task t
        WHERE t.order_id = g.order_id
          AND t.status = 'REJECTED'
        ORDER BY t.seq DESC
        LIMIT 1
    )
WHERE g.status = 'REJECTED'
  AND g.audit_note IS NULL
  AND g.order_id IS NOT NULL
  AND EXISTS (
        SELECT 1
        FROM approval_task t
        WHERE t.order_id = g.order_id
          AND t.status = 'REJECTED'
          AND t.note IS NOT NULL
          AND t.note <> ''
    );
