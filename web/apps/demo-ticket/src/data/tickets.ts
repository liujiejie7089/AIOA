export type TicketStatus = 'OPEN' | 'PROCESSING' | 'CLOSED'

export interface Ticket {
  id: string
  title: string
  status: TicketStatus
  assignee: string
  createdAt: string
  channel: string
  priority: '高' | '中' | '低'
  description: string
}

export const STATUS_LABEL: Record<TicketStatus, string> = {
  OPEN: '待处理',
  PROCESSING: '处理中',
  CLOSED: '已关闭'
}

export const STATUS_OPTIONS: { label: string; value: TicketStatus | 'ALL' }[] = [
  { label: '全部', value: 'ALL' },
  { label: '待处理 OPEN', value: 'OPEN' },
  { label: '处理中 PROCESSING', value: 'PROCESSING' },
  { label: '已关闭 CLOSED', value: 'CLOSED' }
]

export const TICKETS: Ticket[] = [
  {
    id: 'TK-20260101',
    title: '报销单据上传失败，提示附件超限',
    status: 'OPEN',
    assignee: '张伟',
    createdAt: '2026-08-28 09:12',
    channel: '在线客服',
    priority: '高',
    description: '用户反馈上传 12MB 报销附件时报「附件超限」，期望放宽到 20MB 或给出压缩提示。'
  },
  {
    id: 'TK-20260102',
    title: '审批流在第三节点卡住无响应',
    status: 'PROCESSING',
    assignee: '李娜',
    createdAt: '2026-08-28 10:41',
    channel: '电话',
    priority: '高',
    description: '部门总监审批后流程未流转到财务节点，日志显示状态机未推进，已联系后端排查。'
  },
  {
    id: 'TK-20260103',
    title: '希望工单列表支持按处理人批量转派',
    status: 'OPEN',
    assignee: '王强',
    createdAt: '2026-08-29 14:03',
    channel: '邮件',
    priority: '中',
    description: '客服主管需要一次性把某处理人的全部工单转派给他人，当前只能逐条操作。'
  },
  {
    id: 'TK-20260104',
    title: '移动端页面在 iOS 17 上样式错位',
    status: 'PROCESSING',
    assignee: '陈静',
    createdAt: '2026-08-30 08:55',
    channel: '在线客服',
    priority: '中',
    description: '工单详情的操作栏在 iOS 17 Safari 上被底部安全区遮挡，需要适配 env(safe-area-inset-bottom)。'
  },
  {
    id: 'TK-20260105',
    title: '导出 Excel 缺列：创建时间为空',
    status: 'CLOSED',
    assignee: '刘洋',
    createdAt: '2026-08-25 16:20',
    channel: '邮件',
    priority: '低',
    description: '导出模板遗漏创建时间列映射，已修复并上线 v1.4.2。'
  },
  {
    id: 'TK-20260106',
    title: '账号被锁定后无法自助解锁',
    status: 'CLOSED',
    assignee: '赵敏',
    createdAt: '2026-08-24 11:07',
    channel: '电话',
    priority: '中',
    description: '连续 5 次密码错误锁定 30 分钟，已增加短信验证码自助解锁入口。'
  },
  {
    id: 'TK-20260107',
    title: '工单提醒邮件进入垃圾箱',
    status: 'OPEN',
    assignee: '孙鹏',
    createdAt: '2026-09-01 09:30',
    channel: '邮件',
    priority: '低',
    description: '部分客户邮箱把工单提醒判为垃圾邮件，需要配置 SPF/DKIM 并调整发信域名。'
  },
  {
    id: 'TK-20260108',
    title: '统计看板数据与列表口径不一致',
    status: 'PROCESSING',
    assignee: '周涛',
    createdAt: '2026-09-02 15:48',
    channel: '在线客服',
    priority: '中',
    description: '看板按创建时间统计，列表按更新时间排序，导致数量对不上，需统一口径。'
  }
]

export function findTicket(id: string): Ticket | undefined {
  return TICKETS.find((item) => item.id === id)
}
