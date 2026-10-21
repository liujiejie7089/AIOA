<template>
  <div class="home">
    <!-- ============ 顶部：欢迎条 + 四张实时统计 ============ -->
    <section class="wb-welcome">
      <div class="wb-welcome__line">
        <div>
          <div class="wb-welcome__title">你好，{{ auth.displayName }}</div>
          <div class="wb-welcome__sub">欢迎使用 AIOS 智能办公基座 · 企业智能办公一体化平台</div>
        </div>
        <el-button type="primary" @click="assistant.openDrawer()">唤起 AI 助手</el-button>
      </div>
    </section>

    <div class="wb-stats">
      <section v-for="item in stats" :key="item.label" class="wb-stat">
        <div class="wb-stat__label">{{ item.label }}</div>
        <div class="wb-stat__value">{{ item.value }}</div>
        <div class="wb-stat__foot">实时统计</div>
      </section>
    </div>

    <div class="workbench">
    <!-- ============ 1. 最新信息（消息中心同源：含审批通知） ============ -->
    <section class="wb-card">
      <div class="wb-card__head">
        <span class="wb-tab wb-tab--active">
          最新信息<span v-if="noticeUnread" class="wb-count">({{ noticeUnread }})</span>
        </span>
        <span class="wb-head__spacer" />
        <span class="wb-more" @click="more('notices')"><el-icon><Plus /></el-icon>更多信息</span>
      </div>
      <div class="wb-card__body">
        <div v-if="!annLoaded" class="wb-empty"><span class="wb-empty__sub">加载中…</span></div>
        <div v-else-if="notices.length" class="wb-list">
          <div
            v-for="a in notices"
            :key="a.id"
            class="wb-item wb-item--click"
            @click="go('/notifications')"
          >
            <div class="wb-item__title">
              <span v-if="a.unread" class="wb-dot" />{{ a.title || '（无标题通知）' }}
            </div>
            <div class="wb-item__meta">
              <span class="wb-item__tag">{{ noticeTag(a) }}</span>
              <span v-if="a.createdAt">{{ fmtTime(a.createdAt) }}</span>
            </div>
          </div>
        </div>
        <div v-else class="wb-empty">
          <el-icon class="wb-empty__icon"><Notification /></el-icon>
          <div class="wb-empty__title">暂时没有信息</div>
          <div class="wb-empty__sub">审批通知、系统消息会出现在这里</div>
        </div>
      </div>
    </section>

    <!-- ============ 2. 我的会议 / 会议邀请 ============ -->
    <section class="wb-card">
      <div class="wb-card__head">
        <span
          class="wb-tab"
          :class="{ 'wb-tab--active': meetingScope === 'mine' }"
          @click="meetingScope = 'mine'"
          >我的会议</span
        >
        <span
          class="wb-tab"
          :class="{ 'wb-tab--active': meetingScope === 'invited' }"
          @click="meetingScope = 'invited'"
          >会议邀请</span
        >
        <span class="wb-head__spacer" />
        <span class="wb-more" @click="more('meetings')"><el-icon><Plus /></el-icon>更多会议</span>
      </div>
      <div class="wb-card__body">
        <div v-if="!meetingsLoaded" class="wb-empty"><span class="wb-empty__sub">加载中…</span></div>
        <div v-else-if="meetings.length" class="wb-list">
          <div v-for="m in meetings" :key="m.id" class="wb-item">
            <div class="wb-item__title">{{ m.title }}</div>
            <div class="wb-item__meta">
              <span v-if="m.startAt">{{ fmtTime(m.startAt) }}</span>
              <span v-if="m.meetingTypeLabel">{{ m.meetingTypeLabel }}</span>
              <span v-if="m.attendees" class="wb-item__ellipsis">参会：{{ m.attendees }}</span>
            </div>
          </div>
        </div>
        <div v-else class="wb-empty">
          <el-icon class="wb-empty__icon"><Calendar /></el-icon>
          <div class="wb-empty__title">近期没有会议</div>
          <div class="wb-empty__sub">「会议助手」数字人提交的会议会显示在这里</div>
        </div>
      </div>
    </section>

    <!-- ============ 3. 日历 ============ -->
    <section id="wb-calendar-card" class="wb-card">
      <div class="wb-card__body">
        <div class="wb-cal__bar">
          <div class="wb-cal__nav">
            <el-icon class="wb-cal__arrow" @click="prevMonth"><ArrowLeft /></el-icon>
            <span class="wb-cal__title">{{ monthLabel }}</span>
            <el-icon class="wb-cal__arrow" @click="nextMonth"><ArrowRight /></el-icon>
          </div>
          <el-button size="small" @click="goToday">今日</el-button>
        </div>
        <div class="wb-cal__grid">
          <div v-for="wd in weekDays" :key="wd" class="wb-cal__wd">{{ wd }}</div>
          <div
            v-for="cell in calendarCells"
            :key="cell.dateStr"
            class="wb-cal__cell"
            :class="{ 'wb-cal__cell--muted': cell.muted, 'wb-cal__cell--today': cell.dateStr === todayStr }"
          >
            <span class="wb-cal__num">{{ cell.day }}</span>
            <span v-if="scheduleDates.has(cell.dateStr)" class="wb-cal__dot" />
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 4. 待办/待阅/已办/已阅/拟稿/草稿 ============ -->
    <section class="wb-card">
      <div class="wb-card__head">
        <span
          v-for="tab in wfTabs"
          :key="tab.key"
          class="wb-tab"
          :class="{ 'wb-tab--active': wfActive === tab.key }"
          @click="wfActive = tab.key"
          >{{ tab.label }}<span class="wb-count">({{ wfCounts[tab.key] }})</span></span
        >
        <span class="wb-head__spacer" />
        <span class="wb-more" @click="openProcess"><el-icon><Plus /></el-icon>发起流程</span>
      </div>
      <div class="wb-card__body">
        <div v-if="!wfLoaded" class="wb-empty"><span class="wb-empty__sub">加载中…</span></div>
        <div v-else-if="wfList.length" class="wb-list">
          <div v-for="t in wfList" :key="t.id" class="wb-item">
            <div class="wb-item__title">{{ t.title }}</div>
            <div class="wb-item__meta">
              <span v-if="t.bizType" class="wb-item__tag">{{ t.bizType }}</span>
              <span v-if="t.applicantName">{{ t.applicantName }}</span>
              <span v-if="t.createdAt">{{ fmtTime(t.createdAt) }}</span>
              <span v-if="t.status" class="wb-item__tag">{{ t.status }}</span>
            </div>
          </div>
        </div>
        <div v-else class="wb-empty">
          <el-icon class="wb-empty__icon"><Tickets /></el-icon>
          <div class="wb-empty__title">暂时没有工作</div>
          <div v-if="wfActive === 'draft'" class="wb-empty__sub">系统未启用「草稿暂存」，提交即进入审批</div>
        </div>
      </div>
    </section>

    <!-- ============ 5. 知识库文件 ============ -->
    <section class="wb-card">
      <div class="wb-card__head">
        <span class="wb-tab wb-tab--active">知识库文件</span>
        <span class="wb-head__spacer" />
        <span class="wb-more" @click="more('kb')"><el-icon><Plus /></el-icon>更多文件</span>
      </div>
      <div class="wb-card__body">
        <div v-if="!kbLoaded" class="wb-empty"><span class="wb-empty__sub">加载中…</span></div>
        <div v-else-if="kbDocs.length" class="wb-list">
          <div
            v-for="f in kbDocs"
            :key="f.id"
            class="wb-item wb-item--click"
            @click="openKb"
          >
            <div class="wb-item__title">{{ f.name }}</div>
            <div class="wb-item__meta">
              <span class="wb-item__tag">{{ kbTypeLabel(f) }}</span>
              <span v-if="f.sizeBytes">{{ fmtBytes(f.sizeBytes) }}</span>
              <span v-if="f.createdAt">{{ fmtTime(f.createdAt) }}</span>
              <span v-if="f.state !== 'ok'" class="wb-item__tag wb-item__tag--warn">
                {{ f.state === 'wait' ? '解析中' : '解析失败' }}
              </span>
            </div>
          </div>
        </div>
        <div v-else class="wb-empty">
          <el-icon class="wb-empty__icon"><Folder /></el-icon>
          <div class="wb-empty__title">知识库暂无文件</div>
          <span class="wb-empty__link" @click="openKb">点击此处前往知识库上传</span>
        </div>
      </div>
    </section>

    <!-- ============ 6. 日程管理 ============ -->
    <section class="wb-card">
      <div class="wb-card__head">
        <span class="wb-tab wb-tab--active">日程管理</span>
        <span class="wb-head__spacer" />
        <span class="wb-more" @click="more('schedules')"><el-icon><Plus /></el-icon>更多日程</span>
      </div>
      <div class="wb-card__body">
        <div v-if="!todayLoaded" class="wb-empty"><span class="wb-empty__sub">加载中…</span></div>
        <div v-else-if="todaySchedules.length" class="wb-list">
          <div v-for="s in todaySchedules" :key="s.id" class="wb-item">
            <div class="wb-item__title">{{ s.title }}</div>
            <div class="wb-item__meta">
              <span v-if="s.startAt">{{ fmtTime(s.startAt) }}</span>
              <span v-if="s.remark">{{ s.remark }}</span>
            </div>
          </div>
        </div>
        <div v-else class="wb-empty">
          <el-icon class="wb-empty__icon"><Calendar /></el-icon>
          <div class="wb-empty__title">{{ auth.displayName }}，您好！今日无日程。</div>
          <div class="wb-empty__sub">当天没有日程</div>
        </div>
      </div>
    </section>

    <!-- ============ 发起流程弹层 ============ -->
    <el-dialog v-model="processDialog" title="发起流程" width="560px" destroy-on-close>
      <!-- 第一步：选择审批表单 -->
      <div v-if="!selectedForm">
        <div v-if="!formsLoaded" class="wb-empty"><span class="wb-empty__sub">加载可发起的表单…</span></div>
        <div v-else-if="approvalForms.length" class="wb-list">
          <div
            v-for="f in approvalForms"
            :key="f.code"
            class="wb-item"
            style="cursor: pointer"
            @click="chooseForm(f)"
          >
            <div class="wb-item__title">{{ f.name }}</div>
            <div class="wb-item__meta">
              <span v-if="f.description">{{ f.description }}</span>
              <span v-else class="wb-empty__sub">{{ f.code }}</span>
            </div>
          </div>
        </div>
        <div v-else class="wb-empty">
          <el-icon class="wb-empty__icon"><DocumentDelete /></el-icon>
          <div class="wb-empty__title">暂无可发起的审批表单</div>
        </div>
      </div>

      <!-- 第二步：填写动态表单 -->
      <div v-else>
        <div style="font-weight: 600; margin-bottom: 12px; color: var(--aios-text)">
          {{ selectedForm.name }}
          <el-button link type="primary" size="small" @click="selectedForm = null">← 重选</el-button>
        </div>
        <el-form v-if="formRender" label-position="top">
          <el-form-item v-for="fld in formRender.fields" :key="fld.name" :label="fld.label">
            <el-input
              v-if="['text', 'textarea'].includes(fld.type)"
              v-model="formModel[fld.name]"
              :type="fld.type === 'textarea' ? 'textarea' : 'text'"
              :placeholder="fld.placeholder"
            />
            <el-input
              v-else-if="['number', 'amount'].includes(fld.type)"
              v-model="formModel[fld.name]"
              type="number"
              :placeholder="fld.placeholder"
            />
            <el-date-picker
              v-else-if="fld.type === 'date'"
              v-model="formModel[fld.name]"
              type="date"
              value-format="YYYY-MM-DD"
              :placeholder="fld.placeholder || '选择日期'"
              style="width: 100%"
            />
            <el-date-picker
              v-else-if="fld.type === 'datetime'"
              v-model="formModel[fld.name]"
              type="datetime"
              value-format="YYYY-MM-DD HH:mm:ss"
              :placeholder="fld.placeholder || '选择时间'"
              style="width: 100%"
            />
            <el-switch v-else-if="fld.type === 'boolean'" v-model="formModel[fld.name]" />
            <el-select
              v-else-if="fld.type === 'select'"
              v-model="formModel[fld.name]"
              :placeholder="fld.placeholder || '请选择'"
              style="width: 100%"
            >
              <el-option
                v-for="o in fld.options || []"
                :key="String(o.value)"
                :label="String(o.label)"
                :value="o.value"
              />
            </el-select>
            <el-select
              v-else-if="fld.type === 'multiselect'"
              v-model="formModel[fld.name]"
              multiple
              :placeholder="fld.placeholder || '请选择'"
              style="width: 100%"
            >
              <el-option
                v-for="o in fld.options || []"
                :key="String(o.value)"
                :label="String(o.label)"
                :value="o.value"
              />
            </el-select>
            <el-input v-else v-model="formModel[fld.name]" :placeholder="fld.placeholder" />
          </el-form-item>
        </el-form>
        <div v-if="formError" style="color: #e24b4a; font-size: 12px; margin-top: 8px">{{ formError }}</div>
      </div>

      <template #footer>
        <el-button @click="processDialog = false">取消</el-button>
        <el-button
          v-if="selectedForm"
          type="primary"
          :loading="formSubmitting"
          @click="submitProcess"
          >提交</el-button
        >
      </template>
    </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useAppsStore } from '@/stores/apps'
import { useAssistantStore } from '@/stores/assistant'
import { homeStats } from '@/api/resource'
import {
  NOTICE_TYPE_LABEL,
  listNotices,
  listFormSubmissions,
  toMeetingRow,
  toScheduleRow,
  dateKey,
  getWorkflowSummary,
  listWorkflowTasks,
  listKbFiles,
  kbTypeLabel,
  listApprovalForms,
  getApprovalForm,
  submitForm,
  type MeetingRow,
  type ScheduleRow,
  type WorkflowTaskLite,
  type KbDoc,
  type FormTemplate,
  type FormRender,
  type NotificationItem
} from '@/api/portal'

const auth = useAuthStore()
const router = useRouter()
const apps = useAppsStore()
const assistant = useAssistantStore()
/** 当前登录人（「我的会议」「会议邀请」按 id 与显示名判定）。 */
const me = computed(() => ({ id: auth.user?.id, name: auth.displayName }))

function go(path: string) {
  void router.push(path)
}

/* ===================================================================
   顶部四张实时统计（沿用原有口径：待我审批 / AI 会话 / AI 运行 / 已接入应用）
   =================================================================== */
const statNums = ref<{ todoApprovals?: number; aiConversations?: number; aiRuns?: number }>({})

/**
 * 四张卡用 computed 而不是在 loadStats 里一次性拼字符串：
 * 「已接入应用」的源是 apps store（apps.list() 与 loadStats() 是并发发出的），
 * 若在 loadStats 里快照 apps.enabled.length，首屏会先渲染成 0 再被下一次轮询纠正。
 * 绑成 computed 后无论两个请求谁先回来，卡片都会立刻拿到正确值。
 */
const stats = computed(() => {
  const s = statNums.value
  const dash = (v: number | undefined) => (v === undefined ? '—' : String(v))
  // 应用列表未加载成功时同样给占位符，避免把「没加载到」显示成「0 个应用」
  return [
    { label: '待我审批', value: dash(s.todoApprovals) },
    { label: 'AI 会话', value: dash(s.aiConversations) },
    { label: 'AI 运行', value: dash(s.aiRuns) },
    { label: '已接入应用', value: apps.loaded ? String(apps.enabled.length) : '—' }
  ]
})

async function loadStats(silent = false) {
  try {
    const s = await homeStats()
    statNums.value = {
      todoApprovals: s.todoApprovals ?? 0,
      aiConversations: s.aiConversations ?? 0,
      aiRuns: s.aiRuns ?? 0
    }
  } catch {
    // 403 / 后端不可达时保留上一次的值，不用假数据覆盖
    if (!silent && statNums.value.todoApprovals === undefined) {
      statNums.value = { todoApprovals: 0, aiConversations: 0, aiRuns: 0 }
    }
  }
}

/* ===================================================================
   1. 最新信息 —— 消息中心同源接口（GET /notifications）
   ------------------------------------------------------------------
   审批通知（APPROVAL）也走这里：审批人收到「新审批待处理」、发起人收到
   「审批进度更新」，所以管理员在首页就能看到审批通知，不再依赖隐藏菜单。
   =================================================================== */
const notices = ref<NotificationItem[]>([])
const noticeUnread = ref(0)
const annLoaded = ref(false)
/** 时间行标签：审批 / 系统 / 数字员工…（缺省回落到类型码本身）。 */
function noticeTag(n: NotificationItem): string {
  return NOTICE_TYPE_LABEL[n.type] || n.type || '通知'
}
async function loadNotices(silent = false) {
  if (!silent) annLoaded.value = false
  try {
    const res = await listNotices(6)
    notices.value = res.items
    noticeUnread.value = res.unread
  } catch {
    notices.value = []
    noticeUnread.value = 0
  } finally {
    annLoaded.value = true
  }
}

/* ===================================================================
   2. 我的会议 / 会议邀请 —— OA 表单机制「会议助手」(meeting_book) 的真实提交
   ------------------------------------------------------------------
   数据源 = 数字人「会议助手」提交的会议申请（form_submission），
   管理端暂无独立会议页，因此这里直接读同一份业务数据，H5 提交后即刻可见。
   =================================================================== */
const meetingScope = ref<'mine' | 'invited'>('mine')
const allMeetings = ref<MeetingRow[]>([])
const meetingsLoaded = ref(false)
const meetings = computed(() => {
  const list = allMeetings.value.filter((m) => (meetingScope.value === 'mine' ? m.mine : m.invited))
  return list.slice(0, 6)
})
async function loadMeetings(silent = false) {
  if (!silent) meetingsLoaded.value = false
  try {
    const res = await listFormSubmissions('meeting_book', 1, 50)
    allMeetings.value = res.list
      .map((r) => toMeetingRow(r, { id: me.value.id, name: me.value.name }))
      .filter((m) => !!m.startAt)
      .sort((a, b) => String(a.startAt).localeCompare(String(b.startAt)))
  } catch {
    allMeetings.value = []
  } finally {
    meetingsLoaded.value = true
  }
}
watch(meetingScope, () => {
  /* 切 tab 只是本地切分，无请求 */
})


/* ===================================================================
   3. 月历（纯前端手写 grid，从 schedules 接口标记有日程的日期）
   =================================================================== */
const weekDays = ['日', '一', '二', '三', '四', '五', '六']
const today = new Date()
const todayStr = fmtDate(today.getFullYear(), today.getMonth(), today.getDate())
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth()) // 0-based
const scheduleDates = ref<Set<string>>(new Set())

const monthLabel = computed(() => `${viewYear.value}年${viewMonth.value + 1}月`)

function fmtDate(y: number, m0: number, d: number): string {
  const dt = new Date(y, m0, d)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`
}

const calendarCells = computed(() => {
  const y = viewYear.value
  const m = viewMonth.value
  const first = new Date(y, m, 1)
  const startWeekday = first.getDay() // 0=周日
  const daysInMonth = new Date(y, m + 1, 0).getDate()
  const cells: { day: number; muted: boolean; dateStr: string }[] = []
  // 上月灰格补齐
  const prevDays = new Date(y, m, 0).getDate()
  for (let i = startWeekday - 1; i >= 0; i--) {
    const day = prevDays - i
    cells.push({ day, muted: true, dateStr: fmtDate(y, m - 1, day) })
  }
  // 当月
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ day: d, muted: false, dateStr: fmtDate(y, m, d) })
  }
  // 下月灰格补齐到整周
  const trailing = (7 - (cells.length % 7)) % 7
  for (let d = 1; d <= trailing; d++) {
    cells.push({ day: d, muted: true, dateStr: fmtDate(y, m + 1, d) })
  }
  return cells
})

/* 日历打点数据源 = 「工作日历」数字人（calendar_event）的真实提交 + 会议开始日。 */
const calendarEvents = ref<ScheduleRow[]>([])
function recomputeDots() {
  const set = new Set<string>()
  for (const s of calendarEvents.value) {
    const k = dateKey(s.startAt)
    if (k) set.add(k)
  }
  for (const m of allMeetings.value) {
    const k = dateKey(m.startAt)
    if (k) set.add(k)
  }
  scheduleDates.value = set
}
async function loadSchedules() {
  try {
    const res = await listFormSubmissions('calendar_event', 1, 200)
    calendarEvents.value = res.list.map((r) => toScheduleRow(r, { id: me.value.id }))
  } catch {
    calendarEvents.value = []
  }
  recomputeDots()
}

function prevMonth() {
  if (viewMonth.value === 0) {
    viewMonth.value = 11
    viewYear.value--
  } else {
    viewMonth.value--
  }
}
function nextMonth() {
  if (viewMonth.value === 11) {
    viewMonth.value = 0
    viewYear.value++
  } else {
    viewMonth.value++
  }
}
function goToday() {
  viewYear.value = today.getFullYear()
  viewMonth.value = today.getMonth()
}

/* ===================================================================
   4. 待办/待阅/已办/已阅/拟稿/草稿（六 tab 复用 workflow 接口）
   =================================================================== */
const wfTabs = [
  { key: 'todo', label: '待办' },
  { key: 'ccUnread', label: '待阅' },
  { key: 'done', label: '已办' },
  { key: 'ccRead', label: '已阅' },
  { key: 'mine', label: '拟稿' },
  { key: 'draft', label: '草稿' }
] as const
type WfKey = (typeof wfTabs)[number]['key']

const wfCounts = reactive<Record<WfKey, number>>({
  todo: 0,
  ccUnread: 0,
  done: 0,
  ccRead: 0,
  mine: 0,
  draft: 0
})
const wfActive = ref<WfKey>('todo')
const wfList = ref<WorkflowTaskLite[]>([])
const wfLoaded = ref(false)
/** 四个 scope 的结果缓存：切 tab 只是本地切分，不重复打接口。 */
const wfCache: Record<'todo' | 'cc' | 'done' | 'mine', WorkflowTaskLite[]> = {
  todo: [],
  cc: [],
  done: [],
  mine: []
}

function syncWfList() {
  const tab = wfActive.value
  if (tab === 'draft') {
    wfList.value = []
  } else if (tab === 'ccUnread') {
    wfList.value = wfCache.cc.filter((x) => !x.read)
  } else if (tab === 'ccRead') {
    wfList.value = wfCache.cc.filter((x) => x.read)
  } else if (tab === 'mine') {
    wfList.value = wfCache.mine
  } else {
    wfList.value = wfCache[tab]
  }
}

/**
 * 六个计数与列表全部来自「审批中心」同一组接口：
 *   summary → todo / done / ccUnread；tasks?scope=cc 再切已读/未读；scope=mine → 拟稿。
 * 「草稿」后端没有这个概念（没有暂存表），如实显示 0 并在空态说明。
 */
async function loadWf(silent = false) {
  if (!silent) wfLoaded.value = false
  try {
    const [summary, todo, cc, done, mine] = await Promise.all([
      getWorkflowSummary().catch(() => ({ todo: 0, ccUnread: 0, done: 0 }) as never),
      listWorkflowTasks('todo').catch(() => [] as WorkflowTaskLite[]),
      listWorkflowTasks('cc').catch(() => [] as WorkflowTaskLite[]),
      listWorkflowTasks('done').catch(() => [] as WorkflowTaskLite[]),
      listWorkflowTasks('mine').catch(() => [] as WorkflowTaskLite[])
    ])
    wfCache.todo = todo
    wfCache.cc = cc
    wfCache.done = done
    wfCache.mine = mine
    const s = summary as { todo?: number; done?: number; ccUnread?: number }
    wfCounts.todo = Number(s?.todo ?? todo.length)
    wfCounts.done = Number(s?.done ?? done.length)
    wfCounts.ccUnread = cc.filter((x) => !x.read).length
    wfCounts.ccRead = cc.filter((x) => x.read).length
    wfCounts.mine = mine.length
    wfCounts.draft = 0
    syncWfList()
  } catch {
    wfList.value = []
  } finally {
    wfLoaded.value = true
  }
}
watch(wfActive, syncWfList)


/* ===================================================================
   5. 知识库文件（与「知识库」页同一接口 GET /kb/documents）
   ------------------------------------------------------------------
   字段：name（名称）/ icon 或 state（类型）/ sizeBytes（大小）/ createdAt（时间）。
   普通成员只看到自己的文档；租户管理员调 scope=tenant 可看全租户。
   =================================================================== */
const kbDocs = ref<KbDoc[]>([])
const kbLoaded = ref(false)
async function loadKb(silent = false) {
  if (!silent) kbLoaded.value = false
  try {
    const list = await listKbFiles()
    kbDocs.value = list.slice(0, 6)
  } catch {
    kbDocs.value = []
  } finally {
    kbLoaded.value = true
  }
}
function openKb() {
  go('/kb')
}

/* ===================================================================
   6. 今日日程（工作日历提交里开始日 = 今天的条目 + 今天的会议）
   =================================================================== */
const todayLoaded = ref(false)
const todaySchedules = computed(() => {
  const t = todayStr
  const fromCalendar = calendarEvents.value
    .filter((s) => dateKey(s.startAt) === t)
    .map((s) => ({ id: `c${s.id}`, title: s.title, startAt: s.startAt, remark: s.remark }))
  const fromMeeting = allMeetings.value
    .filter((m) => dateKey(m.startAt) === t)
    .map((m) => ({
      id: `m${m.id}`,
      title: m.title,
      startAt: m.startAt,
      remark: m.meetingTypeLabel ? `会议 · ${m.meetingTypeLabel}` : '会议'
    }))
  return [...fromCalendar, ...fromMeeting].sort((a, b) => String(a.startAt).localeCompare(String(b.startAt)))
})


/* ===================================================================
   发起流程弹层（动态表单）
   =================================================================== */
const processDialog = ref(false)
const approvalForms = ref<FormTemplate[]>([])
const formsLoaded = ref(false)
const selectedForm = ref<FormTemplate | null>(null)
const formRender = ref<FormRender | null>(null)
const formModel = reactive<Record<string, unknown>>({})
const formSubmitting = ref(false)
const formError = ref('')

async function openProcess() {
  processDialog.value = true
  selectedForm.value = null
  formRender.value = null
  formError.value = ''
  formsLoaded.value = false
  try {
    approvalForms.value = await listApprovalForms()
  } catch {
    approvalForms.value = []
  } finally {
    formsLoaded.value = true
  }
}

async function chooseForm(f: FormTemplate) {
  selectedForm.value = f
  formRender.value = null
  formError.value = ''
  try {
    const r = await getApprovalForm(f.code)
    formRender.value = r
    for (const k of Object.keys(formModel)) delete formModel[k]
    for (const fld of r.fields || []) {
      formModel[fld.name] =
        fld.type === 'multiselect' ? [] : fld.type === 'boolean' ? false : (fld.default ?? '')
    }
  } catch {
    ElMessage.error('表单加载失败，请稍后重试')
  }
}

async function submitProcess() {
  if (!selectedForm.value || !formRender.value) return
  formSubmitting.value = true
  formError.value = ''
  try {
    await submitForm(selectedForm.value.code, { ...formModel })
    ElMessage.success('已提交，流程发起成功')
    processDialog.value = false
    void loadWf(true)
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '提交失败，请检查表单'
  } finally {
    formSubmitting.value = false
  }
}

/* ===================================================================
   通用
   =================================================================== */
function more(which: string) {
  if (which === 'notices') return go('/notifications')
  if (which === 'kb') return go('/kb')
  // 会议 / 日程：数据来自数字人表单提交，管理端暂无对应独立页面，如实说明而不是假装跳转
  ElMessage.info('会议与日程来自「会议助手 / 工作日历」数字人的表单提交，管理端暂无独立页')
}

function fmtTime(s?: string): string {
  if (!s) return ''
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function fmtBytes(n?: number): string {
  if (!n) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/**
 * 首页统一取数：六格并行拉取，任一失败只让该格空态（不白屏）。
 * 每 60s 静默刷新一次 —— 审批通知、待办计数、知识库入库进度都能自动更新。
 */
async function loadAll(silent = false) {
  await Promise.all([
    loadNotices(silent),
    loadMeetings(silent),
    loadSchedules(),
    loadWf(silent),
    loadKb(silent),
    loadStats(silent)
  ])
  recomputeDots()
  todayLoaded.value = true
}

let autoTimer: number | undefined
onMounted(() => {
  void apps.list()
  void loadAll(false)
  autoTimer = window.setInterval(() => void loadAll(true), 60000)
})
onUnmounted(() => {
  if (autoTimer) window.clearInterval(autoTimer)
})
</script>

<style scoped>
/* ===================================================================
   首页工作台卡片网格（3 列 2 行，窄屏响应式降列）
   样式自包含：仅引用原有 token（--aios-primary / --aios-bg-card 等），
   圆角/背景等写死，不依赖任何新增全局变量。
   =================================================================== */
/* ---------- 顶部欢迎条 + 四张实时统计（沿用原首页视觉，置于六宫格之上） ---------- */
.home {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.wb-welcome {
  background: var(--aios-bg-card);
  border: 1px solid var(--aios-border);
  border-radius: 8px;
  padding: 16px 20px;
}

.wb-welcome__line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.wb-welcome__title {
  font-size: 18px;
  font-weight: 600;
  color: var(--aios-text);
}

.wb-welcome__sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--aios-text-sub);
}

.wb-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 1200px) {
  .wb-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.wb-stat {
  background: var(--aios-bg-card);
  border: 1px solid var(--aios-border);
  border-radius: 8px;
  padding: 16px 20px;
}

.wb-stat__label {
  font-size: 12px;
  color: var(--aios-text-sub);
}

.wb-stat__value {
  margin-top: 10px;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--aios-primary-strong, var(--aios-primary));
}

.wb-stat__foot {
  margin-top: 8px;
  font-size: 11px;
  color: var(--aios-text-sub);
  opacity: 0.7;
}

.workbench {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  grid-auto-rows: 1fr;
  align-items: stretch;
}
@media (max-width: 1200px) {
  .workbench {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .workbench {
    grid-template-columns: minmax(0, 1fr);
  }
}

.wb-card {
  display: flex;
  flex-direction: column;
  background: var(--aios-bg-card);
  border: 1px solid var(--aios-border);
  border-radius: 8px;
  box-shadow: var(--aios-shadow-sm);
  overflow: hidden;
  min-height: 280px;
}

.wb-card__head {
  display: flex;
  align-items: center;
  padding: 12px 16px 0;
  gap: 14px;
}

/* 卡片标题 tab：蓝色文字 + 底部蓝色短下划线 */
.wb-tab {
  position: relative;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--aios-text-sub);
  padding: 0 2px 8px;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.16s;
}

.wb-tab--active {
  color: var(--aios-primary);
}

.wb-tab--active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2.5px;
  border-radius: 2px;
  background: var(--aios-primary);
}

.wb-head__spacer {
  flex: 1;
}

/* 右上角蓝色「⊕ 更多」链接 */
.wb-more {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12.5px;
  color: var(--aios-primary);
  cursor: pointer;
  white-space: nowrap;
  flex: 0 0 auto;
}

.wb-more:hover {
  color: var(--aios-primary-strong);
}

.wb-card__body {
  flex: 1;
  min-height: 0;
  padding: 12px 16px 16px;
  overflow: auto;
}

/* 卡片空态 */
.wb-empty {
  height: 100%;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--aios-text-mute);
  text-align: center;
  padding: 12px;
}

.wb-empty__icon {
  font-size: 46px;
  color: #cdd6e3;
}

.wb-empty__title {
  font-size: 13.5px;
  color: var(--aios-text-sub);
}

.wb-empty__sub {
  font-size: 12px;
  color: #bcc6d6;
}

.wb-empty__link {
  font-size: 12.5px;
  color: var(--aios-primary);
  cursor: pointer;
}

.wb-empty__link:hover {
  color: var(--aios-primary-strong);
  text-decoration: underline;
}

/* 卡片列表 */
.wb-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.wb-item {
  padding: 9px 10px;
  border: 1px solid var(--aios-border);
  border-radius: 8px;
  background: #fff;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.wb-item:hover {
  border-color: var(--aios-primary);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.1);
}

.wb-item__title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--aios-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wb-item__meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--aios-text-sub);
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.wb-item__tag {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--aios-primary-soft);
  color: var(--aios-primary-strong);
}

/* 可点击条目（最新信息 → 消息中心；知识库文件 → 知识库） */
.wb-item--click {
  cursor: pointer;
}

/* 未读通知前的小圆点 */
.wb-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 6px;
  border-radius: 50%;
  background: #e24b4a;
  vertical-align: middle;
}

/* 参会人这类长文本：单行省略，避免把卡片撑高 */
.wb-item__ellipsis {
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 未就绪状态标签（解析中 / 失败） */
.wb-item__tag--warn {
  background: rgba(226, 75, 74, 0.1);
  color: #c03a39;
}

/* 审批六 tab 的计数括号 */
.wb-count {
  font-weight: 600;
}

/* ---------- 月历 ---------- */
.wb-cal__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.wb-cal__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--aios-text);
}

.wb-cal__nav {
  display: flex;
  align-items: center;
  gap: 6px;
}

.wb-cal__arrow {
  font-size: 18px;
  color: var(--aios-text-sub);
  cursor: pointer;
  transition: color 0.16s;
}

.wb-cal__arrow:hover {
  color: var(--aios-primary);
}

.wb-cal__grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
}

.wb-cal__wd {
  text-align: center;
  font-size: 12px;
  color: var(--aios-text-sub);
  padding: 4px 0;
}

.wb-cal__cell {
  position: relative;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12.5px;
  color: var(--aios-text);
  border-radius: 8px;
  cursor: default;
}

.wb-cal__cell--muted {
  color: #c2cad6;
}

.wb-cal__cell--today .wb-cal__num {
  width: 24px;
  height: 24px;
  line-height: 24px;
  text-align: center;
  border-radius: 50%;
  background: var(--aios-primary);
  color: #fff;
  font-weight: 600;
}

.wb-cal__dot {
  position: absolute;
  bottom: 3px;
  left: 50%;
  transform: translateX(-50%);
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--aios-primary);
}
</style>

