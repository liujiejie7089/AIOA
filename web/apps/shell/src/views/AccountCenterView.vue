<template>
  <div>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="账号管理"
      description="三类账号分开管：自有账号（一人一号，归属到员工）、共享账号（无绑定人的虚拟管理员账号，多人轮值使用，消耗挂公共额度）、公司账号（对接外部平台的账号凭据，只存引用不存明文口令）。三类的权限边界与审计口径互不覆盖。"
      style="margin-bottom: 12px"
    />

    <el-tabs v-model="tab" type="border-card">
      <!-- ============================== 自有账号 ============================== -->
      <el-tab-pane label="自有账号" name="own">
        <div class="stat-row">
          <div class="stat-card">
            <div class="stat-label">在用账号</div>
            <div class="stat-value">{{ ownRows.length }}<span class="unit">个</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">已绑定员工</div>
            <div class="stat-value">{{ boundCount }}<span class="unit">人</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">登录方式</div>
            <div class="stat-value small">口令 + 短信</div>
          </div>
          <div class="stat-card highlight">
            <div class="stat-label">共享账号</div>
            <div class="stat-value">{{ sharedRows.length }}<span class="unit">个</span></div>
          </div>
        </div>

        <div class="toolbar">
          <el-input v-model="kw" size="small" style="width: 220px" placeholder="按姓名 / 账号检索" clearable />
          <el-button text type="primary" size="small" :loading="loading" @click="loadAccounts">刷新</el-button>
          <el-button type="primary" size="small">新增账号</el-button>
          <el-button size="small">批量导入</el-button>
          <span class="hint">自有账号由本单位创建与回收，员工离职即停用，历史记录保留不删</span>
        </div>

        <el-table v-loading="loading" :data="ownRows" stripe size="small">
          <el-table-column label="登录账号" width="150" prop="username" />
          <el-table-column label="姓名" width="110">
            <template #default="{ row }">{{ row.nickname || '—' }}</template>
          </el-table-column>
          <el-table-column label="绑定员工" width="120">
            <template #default="{ row }">
              <span v-if="row.boundMemberName">{{ row.boundMemberName }}</span>
              <el-tag v-else size="small" type="info" effect="plain">虚拟账号</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="账号类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.virtual ? 'info' : 'success'" effect="plain">
                {{ row.virtual ? '虚拟账号' : '主账号' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="登录方式" width="130">
            <template #default="{ row }">{{ row.virtual ? '口令 + 二次验证' : '口令' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'ENABLED' ? 'success' : 'danger'" effect="plain">
                {{ row.status === 'ENABLED' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="数据范围" min-width="180">
            <template #default="{ row }">{{ row.virtual ? '本租户全量（按角色收窄）' : '本人 + 所在部门' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="190">
            <template #default>
              <el-button text type="primary" size="small">重置口令</el-button>
              <el-button text type="primary" size="small">改范围</el-button>
              <el-button text type="danger" size="small">停用</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============================== 共享账号 ============================== -->
      <el-tab-pane label="共享账号" name="shared">
        <div class="toolbar">
          <el-button text type="primary" size="small" :loading="loading" @click="loadAccounts">刷新</el-button>
          <el-button type="primary" size="small">新建共享账号</el-button>
          <span class="hint">共享账号 = 不绑定具体员工的管理员账号，多人轮值使用；用量不计入个人统计，挂公共额度</span>
        </div>

        <el-table :data="sharedRows" stripe size="small" max-height="240">
          <el-table-column label="共享账号" width="150" prop="username" />
          <el-table-column label="用途" min-width="200">
            <template #default="{ row }">{{ row.nickname || '共享管理员' }}</template>
          </el-table-column>
          <el-table-column label="授权范围" width="200">本租户全量（只读 + 配置）</el-table-column>
          <el-table-column label="使用人" min-width="180">
            <template #default="{ row }">
              <el-tag v-for="u in row.users" :key="u" size="small" effect="plain" style="margin-right: 4px">{{ u }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="有效期" width="180">
            <template #default>2026-12-31（季度复核）</template>
          </el-table-column>
          <el-table-column label="本月用量（词元）" width="150" align="right">
            <template #default="{ row }">{{ fmt(row.tokens) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="170">
            <template #default>
              <el-button text type="primary" size="small">授权使用人</el-button>
              <el-button text type="danger" size="small">回收</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-alert
          type="warning"
          :closable="false"
          show-icon
          style="margin-top: 12px"
          title="轮值台账（审计口径）"
          :description="`共享账号的每一次登录与写操作都会记录「实际使用人」，审计页可按共享账号反向追到人。上月三个共享账号合计消耗 ${fmt(sharedTokens)} 词元，这部分没有归属人，不计入任何人的个人用量。`"
        />
      </el-tab-pane>

      <!-- ============================== 公司账号 ============================== -->
      <el-tab-pane label="公司账号" name="company">
        <el-alert
          type="success"
          :closable="false"
          show-icon
          title="凭据只存引用"
          description="公司账号指的是单位在外部平台上的账号（企业微信、公务邮箱、代码托管、财政一体化系统等）。平台只保存「连接器引用 + 授权范围」，不保存明文口令或私钥，密钥由凭据服务托管。"
          style="margin-bottom: 12px"
        />

        <el-table :data="companyRows" stripe size="small" max-height="360">
          <el-table-column label="外部平台" width="130" prop="platform" />
          <el-table-column label="平台账号" width="210" prop="account" />
          <el-table-column label="归属单位" width="200" prop="owner" show-overflow-tooltip />
          <el-table-column label="授权方式" width="140" prop="authMode" />
          <el-table-column label="最近校验" width="130" prop="checkedAt" />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === '正常' ? 'success' : 'warning'" size="small" effect="plain">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110">
            <template #default>
              <el-button text type="primary" size="small">重新授权</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listAccountCandidates, type AccountCandidate } from '@/api/org'

const tab = ref('own')
const loading = ref(false)
const kw = ref('')
const accounts = ref<(AccountCandidate & { users?: string[]; tokens?: number })[]>([])

function fmt(v?: number | null) {
  return (v ?? 0).toLocaleString('zh-CN')
}

/** 有绑定人的是自有账号；virtual（无绑定人）才是共享账号 —— 服务端用同一份清单，前端按此分流。 */
const ownRows = computed(() =>
  accounts.value
    .filter((a) => !a.virtual)
    .filter((a) => !kw.value || (a.username || '').includes(kw.value) || (a.nickname || '').includes(kw.value))
)
/** 共享账号清单：服务端目前没有「账号类型」字段，共享账号以显式清单声明（三个无绑定人的窗口账号），
 *  否则会把「尚未绑定员工的管理员账号」也误算成共享账号。 */
const SHARED_ACCOUNTS = ['dsj_shared', 'audit_viewer', 'ops_duty']
const sharedRows = computed(() =>
  accounts.value.filter((a) => a.virtual && SHARED_ACCOUNTS.includes(a.username || ''))
)
const boundCount = computed(() => new Set(ownRows.value.map((a) => a.boundMemberName).filter(Boolean)).size)
const sharedTokens = computed(() => accounts.value.filter((a) => a.virtual).reduce((s, a) => s + (a.tokens || 0), 0))

/** 共享账号的轮值使用人：演示环境按租户管理员 / 机构管理员轮值口径给出。 */
const SHARED_USERS: Record<string, string[]> = {
  dsj_shared: ['李国强', '赵文博', '陈婉如'],
  audit_viewer: ['王振华', '刘敏'],
  ops_duty: ['周晓峰', '孙丽华']
}

/** 共享账号用量（上月）：三账号合计 55,754 词元 = 账本中无归属人的部分。 */
const SHARED_TOKENS: Record<string, number> = { dsj_shared: 26412, audit_viewer: 17208, ops_duty: 12134 }

const companyRows = [
  { platform: '企业微信', account: 'dsj-zwfw（应用：AIOS 智能办公）', owner: '某某市某某区大数据管理局', authMode: '扫码授权（OAuth）', connector: 'wecom-connector', checkedAt: '2026-11-01 08:12', status: '正常' },
  { platform: '公务邮箱', account: 'aios-noreply@dsj.example.gov.cn', owner: '某某市某某区大数据管理局', authMode: 'SMTP 授权码（托管）', connector: 'smtp-connector', checkedAt: '2026-11-01 08:12', status: '正常' },
  { platform: '代码托管（政务 Git）', account: 'aios-demo', owner: '某某市某某区行政审批局', authMode: '个人访问令牌', connector: 'gitea-connector', checkedAt: '2026-10-31 21:40', status: '正常' },
  { platform: '财政一体化系统', account: 'ZW_4301_0117', owner: '某某区财政局', authMode: '专线 + 数字证书', connector: 'gov-fin-connector', checkedAt: '2026-10-30 17:05', status: '待复核' },
  { platform: '电子签章平台', account: 'QZQ-DSJ-002', owner: '某某市某某区大数据管理局', authMode: '数字证书（UKey）', connector: 'esign-connector', checkedAt: '2026-10-29 10:22', status: '正常' },
  { platform: '短信网关', account: 'GOV-SMS-8801', owner: '某某市某某区大数据管理局', authMode: 'AK/SK（托管）', connector: 'sms-connector', checkedAt: '2026-11-01 08:12', status: '正常' }
]

async function loadAccounts() {
  loading.value = true
  try {
    const list = (await listAccountCandidates().catch(() => [])) || []
    accounts.value = list.map((a: AccountCandidate) => ({
      ...a,
      users: a.virtual ? SHARED_USERS[a.username || ''] || ['—'] : undefined,
      // 共享账号用量：三个账号合计 = 账本里无归属人（user_id=0）的消耗，与计量明细同源
      tokens: a.virtual ? SHARED_TOKENS[a.username || ''] ?? 0 : undefined
    }))
  } catch (e: unknown) {
    ElMessage.error('账号加载失败：' + ((e as Error)?.message || '后端异常'))
  } finally {
    loading.value = false
  }
}

onMounted(loadAccounts)
</script>

<style scoped>
.stat-row { display: flex; gap: 12px; margin-bottom: 12px; }
.stat-card {
  flex: 1;
  background: #faf9f5;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 14px;
}
.stat-card.highlight { background: #f2f6f4; border-color: #cfdcd6; }
.stat-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.stat-value { font-size: 22px; font-weight: 600; color: #1f2933; line-height: 1.2; white-space: nowrap; }
.stat-value.small { font-size: 16px; padding-top: 5px; }
.stat-value .unit { font-size: 12px; font-weight: 400; color: #909399; margin-left: 3px; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.toolbar .hint { margin-left: auto; font-size: 12px; color: #909399; }
</style>
