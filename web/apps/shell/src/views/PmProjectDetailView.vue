<template>
  <div v-loading="loading">
    <el-page-header @back="router.push('/pm/projects')" style="margin-bottom: 12px">
      <template #content>
        <span style="font-weight: 500">{{ project?.name || '项目详情' }}</span>
        <el-tag v-if="project" size="small" effect="plain" style="margin-left: 8px">
          {{ PM_PROJECT_TYPE_LABEL[project.projectType] || project.projectType }}
        </el-tag>
        <el-tag v-if="project" :type="PM_PROJECT_STATUS_TAG[project.status] || 'info'" size="small" style="margin-left: 6px">
          {{ PM_PROJECT_STATUS_LABEL[project.status] || project.status }}
        </el-tag>
        <span v-if="project?.myRole" class="hint" style="margin-left: 8px">我的角色：{{ PM_PROJECT_ROLE_LABEL[project.myRole] || project.myRole }}</span>
      </template>
    </el-page-header>

    <el-tabs v-model="tab">
      <!-- ============================ 概览 ============================ -->
      <el-tab-pane label="概览" name="overview">
        <el-card shadow="never">
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="项目编号">{{ project?.projectNo }}</el-descriptions-item>
            <el-descriptions-item label="负责人">{{ project?.ownerName || '—' }}</el-descriptions-item>
            <el-descriptions-item label="预算总额">{{ fmtMoney(project?.budgetAmount) }}</el-descriptions-item>
            <el-descriptions-item label="开始日期">{{ project?.startDate || '—' }}</el-descriptions-item>
            <el-descriptions-item label="结束日期">{{ project?.endDate || '—' }}</el-descriptions-item>
            <el-descriptions-item label="任务完成">{{ project?.taskDoneCount || 0 }} / {{ project?.taskCount || 0 }}</el-descriptions-item>
            <el-descriptions-item label="成员数">{{ project?.memberCount || 0 }}</el-descriptions-item>
            <el-descriptions-item label="类型">{{ PM_PROJECT_TYPE_LABEL[project?.projectType || ''] || '—' }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ PM_PROJECT_STATUS_LABEL[project?.status || ''] || '—' }}</el-descriptions-item>
          </el-descriptions>
          <p v-if="project?.description" class="desc">{{ project.description }}</p>

          <div style="margin-top: 12px">
            <el-select v-model="newStatus" size="small" placeholder="变更状态" style="width: 160px">
              <el-option v-for="s in PM_PROJECT_STATUS" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
            <el-button size="small" :disabled="!project?.canManage" @click="changeStatus">变更状态</el-button>
            <span v-if="!project?.canManage" class="hint" style="margin-left: 8px">仅项目负责人/项目经理或机构管理员及以上可操作</span>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- ==================== 仓库（仅开发项目渲染） ====================
           ★ 2026-10-03：本页签 = 代码仓库的**日常使用入口**。
           原先管理端还有一级菜单「项目与仓库」，与「项目管理」重复（同一个仓库两处入口，
           用户会以为存在两套）。现在菜单里那一项已撤掉，仓库跟着「开发项目」出现；
           租户级配置（企业初始化 / 组织 / 令牌 / 校准）在「系统配置 → 仓库配置」。 -->
      <el-tab-pane v-if="isDev" label="代码仓库" name="repos">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>本项目仓库</span>
              <div>
                <el-button size="small" @click="router.push('/gitee/projects')">仓库总览与配置</el-button>
                <el-button v-if="project?.canManage" size="small" type="primary" @click="openBind">绑定仓库</el-button>
              </div>
            </div>
          </template>
          <!-- 平台级 Webhook 回调地址未配置：这是「仓库建出来了、却停在未就绪」的根因。
               放在这里，是因为 FAILED 行**正是在本页签被看到**的 —— 只提示在「仓库配置」页，
               用户仍会先在本页签对着一行「未就绪」发懵。判据取后端 /gitee/config（单一事实源）。 -->
          <el-alert
            v-if="webhookBaseUrlOk === false"
            type="warning"
            :closable="false"
            show-icon
            title="平台 Webhook 回调地址未配置：新建/重试的仓库会停在「未就绪」"
            style="margin-bottom: 8px"
          >
            <div class="hint">
              建仓本身会成功，但「配置 Webhook」这步必然失败（{{ giteeProviderLabel }} 无法回调本机地址）。
              需由管理员在「系统配置 → 仓库配置」完成 <code>{{ giteeConfigKey }}.webhook-base-url</code> 配置后，
              再对本页「未就绪」的仓库点「重试建仓」。
            </div>
          </el-alert>
          <el-table :data="boundRepos" size="small">
            <el-table-column prop="name" label="仓库名" min-width="150" />
            <el-table-column label="路径" min-width="190">
              <template #default="{ row }">{{ [row.gitee_owner, row.gitee_repo].filter(Boolean).join('/') || '—' }}</template>
            </el-table-column>
            <el-table-column prop="default_branch" label="默认分支" width="100" />
            <el-table-column label="状态" width="96">
              <template #default="{ row }">
                <el-tag size="small" :type="GITEE_PROJECT_STATUS_TAG[row.status] || 'info'">
                  {{ GITEE_PROJECT_STATUS_LABEL[row.status] || row.status || '—' }}
                </el-tag>
              </template>
            </el-table-column>
            <!-- 失败原因：建仓/配置 Webhook 失败时后端写在 error_msg 里（人话，含后续怎么办）。
                 不展示它，用户只会看到「创建失败」而没有下一步。 -->
            <el-table-column label="失败原因" min-width="230">
              <template #default="{ row }">
                <span v-if="row.error_msg" class="repo-error">{{ row.error_msg }}</span>
                <span v-else class="hint">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-link v-if="row.gitee_html_url" :href="row.gitee_html_url" target="_blank" type="primary" style="margin-right: 8px">打开</el-link>
                <el-button size="small" text type="primary" @click="router.push('/gitee/projects/' + row.id)">详情</el-button>
                <el-button v-if="row.status && row.status !== 'ACTIVE'" size="small" text type="warning" @click="retryRepo(row)">重试建仓</el-button>
                <el-button v-if="project?.canManage" size="small" text type="danger" @click="unbind(row)">解绑</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div style="padding: 16px 0" class="hint">尚未绑定代码仓库</div>
            </template>
          </el-table>
          <p class="hint" style="margin: 10px 0 0">
            自动建仓要求项目有真实归属部门（仓库名由部门派生）；企业组织或令牌未就绪时，
            先到「仓库总览与配置」完成初始化，再回来点「重试建仓」。
          </p>
        </el-card>
      </el-tab-pane>

      <!-- ============================ 任务 ============================ -->
      <el-tab-pane :label="`任务（${tasks.length}）`" name="tasks">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>任务列表</span>
              <el-button v-if="taskList?.canManage" size="small" type="primary" @click="openTask()">新建任务</el-button>
            </div>
          </template>
          <el-table :data="tasks" size="small">
            <el-table-column prop="title" label="任务" min-width="200" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="PM_TASK_STATUS_TAG[row.status] || 'info'" size="small">
                  {{ PM_TASK_STATUS_LABEL[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="优先级" width="90">
              <template #default="{ row }">{{ PM_TASK_PRIORITY_LABEL[row.priority || ''] || '—' }}</template>
            </el-table-column>
            <el-table-column label="负责人" width="120">
              <template #default="{ row }">{{ memberName(row.assigneeMemberId) }}</template>
            </el-table-column>
            <el-table-column label="进度" width="90">
              <template #default="{ row }">{{ row.progress ?? 0 }}%</template>
            </el-table-column>
            <!-- 仓库列只对开发项目展示（与后端返回口径一致：业务项目的 repoId 恒为 null） -->
            <el-table-column v-if="isDev" label="关联 Issue" width="130">
              <template #default="{ row }">{{ row.repoIssueNo || '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-select
                  :model-value="row.status"
                  size="small"
                  style="width: 110px"
                  @change="(v: string) => changeTaskStatus(row, v)"
                >
                  <el-option v-for="s in PM_TASK_STATUS" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
                <el-button size="small" text type="primary" @click="openTask(row)">编辑</el-button>
                <el-button size="small" text type="danger" @click="removeTask(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div style="padding: 16px 0" class="hint">暂无任务</div>
            </template>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============================ 成员 ============================ -->
      <el-tab-pane :label="`成员（${members.length}）`" name="members">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>项目成员</span>
              <el-button v-if="memberList?.canManage" size="small" type="primary" @click="openAddMember">添加成员</el-button>
            </div>
          </template>
          <el-alert
            v-if="memberList?.repoSyncNote"
            type="info"
            :closable="false"
            show-icon
            :title="memberList.repoSyncNote"
            style="margin-bottom: 8px"
          />
          <el-table :data="members" size="small">
            <el-table-column prop="name" label="姓名" width="120" />
            <el-table-column prop="employeeNo" label="工号" width="120" />
            <el-table-column prop="jobTitle" label="职务" width="140" />
            <el-table-column label="项目角色" width="150">
              <template #default="{ row }">
                <el-select
                  :model-value="row.roleCode"
                  size="small"
                  :disabled="!memberList?.canManage"
                  @change="(v: string) => changeMemberRole(row, v)"
                >
                  <el-option v-for="r in memberList?.roleOptions || []" :key="r.value" :label="r.label" :value="r.value" />
                </el-select>
              </template>
            </el-table-column>
            <!-- 仓库同步列只对开发项目展示 -->
            <el-table-column v-if="isDev" label="仓库同步" width="110">
              <template #default="{ row }">{{ PM_REPO_SYNC_STATUS_LABEL[row.repoSyncStatus || ''] || row.repoSyncStatus || '—' }}</template>
            </el-table-column>
            <el-table-column prop="joinedAt" label="加入时间" width="120" />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button v-if="memberList?.canManage" size="small" text type="danger" @click="removeMember(row)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ 文档（批次 3 / docs/43）：企业级公共（只读挂载）+ 项目专属（可写） ============ -->
      <el-tab-pane label="文档" name="docs">
        <el-card shadow="never" v-loading="docLoading">
          <div style="display: flex; gap: 16px; align-items: flex-start">
            <div style="width: 260px; min-height: 240px; border-right: 1px solid var(--el-border-color-lighter); padding-right: 12px">
              <el-tree
                :data="docTreeData"
                node-key="key"
                :props="{ label: 'label', children: 'children' }"
                :current-node-key="selectedDocKey"
                highlight-current
                default-expand-all
                @node-click="onDocNodeClick"
              />
            </div>
            <div style="flex: 1; min-width: 0">
              <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px">
                <span style="font-weight: 600">{{ selectedDocName || '（请选择文件夹）' }}</span>
                <el-tag v-if="selectedDocReadonly" type="info" size="small">只读（企业级公共）</el-tag>
                <div style="flex: 1"></div>
                <template v-if="!selectedDocReadonly && docTree?.canManage">
                  <el-button size="small" @click="newFolderVisible = true">新建文件夹</el-button>
                  <el-button size="small" type="primary" :loading="uploading" @click="triggerUpload">上传文档</el-button>
                  <el-button size="small" @click="aiDocVisible = true">AI 创建</el-button>
                </template>
                <span v-if="selectedDocReadonly" class="hint" style="font-size: 12px">
                  企业级公共文档请在「企业文档」页维护
                </span>
              </div>
              <input ref="fileInputRef" type="file" style="display: none" @change="onFilePicked" />
              <el-table :data="selectedDocs" size="small" empty-text="该文件夹暂无文档">
                <el-table-column prop="name" label="名称" min-width="200" />
                <el-table-column label="来源" width="120">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.source === 'AI' ? 'success' : 'info'">
                      {{ row.source === 'AI' ? '大模型创建' : '外部上传' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="版本" width="70">
                  <template #default="{ row }">v{{ row.version }}</template>
                </el-table-column>
                <el-table-column label="操作" width="140">
                  <template #default="{ row }">
                    <el-button link size="small" type="primary" @click="previewDoc(row)">查看</el-button>
                    <el-button
                      v-if="!selectedDocReadonly && docTree?.canManage"
                      link
                      size="small"
                      type="danger"
                      @click="removeDoc(row)"
                    >
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </el-card>

        <el-dialog v-model="newFolderVisible" title="新建文件夹" width="420px">
          <el-input v-model="newFolderName" placeholder="文件夹名称" />
          <template #footer>
            <el-button size="small" @click="newFolderVisible = false">取消</el-button>
            <el-button size="small" type="primary" :loading="savingDoc" @click="doCreateFolder">创建</el-button>
          </template>
        </el-dialog>

        <el-dialog v-model="aiDocVisible" title="AI 创建文档" width="640px">
          <el-form label-width="72px" size="small">
            <el-form-item label="名称"><el-input v-model="aiDocForm.name" placeholder="文档名称" /></el-form-item>
            <el-form-item label="正文">
              <el-input
                v-model="aiDocForm.contentText"
                type="textarea"
                :rows="10"
                placeholder="正文由项目数字人生成后回填到此处（生成侧接线见 docs/43 §5）"
              />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button size="small" @click="aiDocVisible = false">取消</el-button>
            <el-button size="small" type="primary" :loading="savingDoc" @click="doCreateAiDoc">保存</el-button>
          </template>
        </el-dialog>

        <el-dialog v-model="docPreviewVisible" :title="docPreview?.name || '文档'" width="720px">
          <pre v-if="docPreview?.contentText" style="white-space: pre-wrap; max-height: 60vh; overflow: auto">{{ docPreview.contentText }}</pre>
          <el-empty v-else description="该文档为外部上传，请下载查看" />
        </el-dialog>
      </el-tab-pane>

      <!-- ======= 经费（批次 4 / docs/43 §4）：追加式流水，红冲纠错，无修改入口 ======= -->
      <el-tab-pane :label="`经费（${expenses.length}）`" name="expenses">
        <el-card shadow="never" v-loading="expenseLoading">
          <el-alert
            v-if="expenseList?.summary.overrun"
            type="warning"
            :closable="false"
            show-icon
            title="累计支出已超预算（仅警示，不阻断继续录入）"
            style="margin-bottom: 10px"
          />
          <el-row :gutter="12" style="margin-bottom: 12px">
            <el-col :span="6"><el-statistic title="预算总额" :value="Number(expenseList?.summary.budgetAmount || 0)" /></el-col>
            <el-col :span="6"><el-statistic title="累计收入" :value="Number(expenseList?.summary.totalIncome || 0)" /></el-col>
            <el-col :span="6"><el-statistic title="累计支出" :value="Number(expenseList?.summary.totalOutcome || 0)" /></el-col>
            <el-col :span="6"><el-statistic title="结余" :value="Number(expenseList?.summary.balance || 0)" /></el-col>
          </el-row>
          <div class="card-header" style="margin-bottom: 8px">
            <div>
              <el-select v-model="expenseFilter.direction" clearable placeholder="方向" size="small" style="width: 110px" @change="loadExpenses">
                <el-option v-for="d in expenseList?.summary.directions || []" :key="d.value" :label="d.label" :value="d.value" />
              </el-select>
              <el-select v-model="expenseFilter.category" clearable placeholder="分类" size="small" style="width: 150px; margin-left: 8px" @change="loadExpenses">
                <el-option v-for="c in expenseList?.summary.categories || []" :key="c.value" :label="c.label" :value="c.value" />
              </el-select>
            </div>
            <el-button v-if="expenseList?.canManage" size="small" type="primary" @click="openExpense">追加流水</el-button>
          </div>
          <el-table :data="expenses" size="small">
            <el-table-column prop="occurredAt" label="发生日期" width="110" />
            <el-table-column label="方向" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.direction === 'IN' ? 'success' : 'warning'">{{ row.directionLabel }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="分类" width="130">
              <template #default="{ row }">{{ row.categoryLabel }}</template>
            </el-table-column>
            <el-table-column label="金额" width="130" align="right">
              <template #default="{ row }">
                <span :class="row.isReversal ? 'hint' : (row.direction === 'IN' ? 'money-in' : 'money-out')">{{ fmtMoney(row.amount) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="分摊比例" width="100">
              <template #default="{ row }">{{ row.allocRatio != null ? row.allocRatio : '—' }}</template>
            </el-table-column>
            <el-table-column label="来源" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.isReversal" size="small" type="info">红冲</el-tag>
                <el-tag v-else-if="row.contractPaymentId" size="small" type="success">合同自动</el-tag>
                <span v-else class="hint">手工录入</span>
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="摘要" min-width="180" show-overflow-tooltip />
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="expenseList?.canManage && !row.isReversal"
                  size="small"
                  text
                  type="danger"
                  @click="reverseExpense(row)"
                >红冲</el-button>
              </template>
            </el-table-column>
            <template #empty><div style="padding: 16px 0" class="hint">暂无经费流水</div></template>
          </el-table>
          <p class="hint" style="margin: 10px 0 0">
            经费流水为<b>追加式账目</b>：已录入的流水不可修改、不可删除；录入有误请用「红冲」追加一条同方向的<b>负额（红字）</b>流水纠正，原行保留可追溯。
          </p>
        </el-card>

        <el-dialog v-model="expenseVisible" title="追加经费流水" width="520px">
          <el-form label-width="90px" size="small">
            <el-form-item label="方向" required>
              <el-radio-group v-model="expenseForm.direction">
                <el-radio value="OUT">支出</el-radio>
                <el-radio value="IN">收入</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="分类" required>
              <el-select v-model="expenseForm.category" style="width: 100%">
                <el-option v-for="c in expenseList?.summary.categories || []" :key="c.value" :label="c.label" :value="c.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="金额" required>
              <el-input-number v-model="expenseForm.amount" :min="0" :precision="2" style="width: 100%" />
            </el-form-item>
            <el-form-item label="发生日期">
              <el-date-picker v-model="expenseForm.occurredAt" type="date" value-format="YYYY-MM-DD" placeholder="默认今天" style="width: 100%" />
            </el-form-item>
            <el-form-item label="分摊比例">
              <el-input-number v-model="expenseForm.allocRatio" :min="0" :precision="2" :controls="false" placeholder="分摊/占比，可留空" style="width: 100%" />
            </el-form-item>
            <el-form-item label="摘要">
              <el-input v-model="expenseForm.remark" type="textarea" :rows="2" placeholder="费用明细说明" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button size="small" @click="expenseVisible = false">取消</el-button>
            <el-button size="small" type="primary" :loading="savingExpense" @click="saveExpense">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ============ 合同（批次 4 / docs/43 §4）：采购付款 / 收款 + 收付款明细（BR-09） ============ -->
      <el-tab-pane :label="`合同（${contracts.length}）`" name="contracts">
        <el-card shadow="never" v-loading="contractLoading">
          <template #header>
            <div class="card-header">
              <el-select v-model="contractFilter.direction" clearable placeholder="方向" size="small" style="width: 150px" @change="loadContracts">
                <el-option v-for="d in contractList?.directions || []" :key="d.value" :label="d.label" :value="d.value" />
              </el-select>
              <el-button v-if="contractList?.canManage" size="small" type="primary" @click="openContract()">新建合同</el-button>
            </div>
          </template>
          <el-table :data="contracts" size="small">
            <el-table-column prop="contractNo" label="合同编号" width="140" />
            <el-table-column prop="name" label="合同名称" min-width="180" show-overflow-tooltip />
            <el-table-column label="方向" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="row.direction === 'IN' ? 'success' : 'warning'">{{ row.directionLabel }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="partyName" label="对方单位" min-width="140" show-overflow-tooltip />
            <el-table-column label="金额" width="130" align="right">
              <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.statusLabel }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openPayments(row)">收付款</el-button>
                <el-button v-if="contractList?.canManage" size="small" text type="primary" @click="openContract(row)">编辑</el-button>
                <el-select
                  v-if="contractList?.canManage && row.status !== 'CLOSED' && row.status !== 'TERMINATED'"
                  :model-value="row.status"
                  size="small"
                  style="width: 104px"
                  @change="(v: string) => changeContractStatus(row, v)"
                >
                  <el-option v-for="s in contractList?.statuses || []" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </template>
            </el-table-column>
            <template #empty><div style="padding: 16px 0" class="hint">暂无合同</div></template>
          </el-table>
          <p class="hint" style="margin: 10px 0 0">
            确认收付款时，系统会在同一事务内自动生成一条经费流水（单一事实源），无需重复登记；已确认的收付款不可修改，只能红冲。
          </p>
        </el-card>

        <el-dialog v-model="contractVisible" :title="contractForm.id ? '编辑合同' : '新建合同'" width="600px">
          <el-form label-width="90px" size="small">
            <el-form-item label="合同编号" required>
              <el-input v-model="contractForm.contractNo" :disabled="!!contractForm.id" placeholder="全企业唯一，如 HT-2026-001" />
            </el-form-item>
            <el-form-item label="合同名称" required><el-input v-model="contractForm.name" /></el-form-item>
            <el-form-item label="方向" required>
              <el-radio-group v-model="contractForm.direction" :disabled="!!contractForm.id">
                <el-radio value="OUT">采购付款</el-radio>
                <el-radio value="IN">收款</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="对方单位"><el-input v-model="contractForm.partyName" /></el-form-item>
            <el-form-item label="合同金额">
              <el-input-number v-model="contractForm.amount" :min="0" :precision="2" style="width: 100%" />
            </el-form-item>
            <el-form-item label="签订日期">
              <el-date-picker v-model="contractForm.signedAt" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button size="small" @click="contractVisible = false">取消</el-button>
            <el-button size="small" type="primary" :loading="savingContract" @click="saveContract">保存</el-button>
          </template>
        </el-dialog>

        <el-dialog v-model="payVisible" :title="`收付款明细 - ${currentContract?.name || ''}`" width="780px">
          <div style="margin-bottom: 10px">
            <el-button v-if="contractList?.canManage" size="small" type="primary" @click="openAddPayment">新增期次</el-button>
          </div>
          <el-table :data="payments" size="small">
            <el-table-column prop="seq" label="期次" width="60" />
            <el-table-column label="计划金额" width="130" align="right">
              <template #default="{ row }">{{ fmtMoney(row.planAmount) }}</template>
            </el-table-column>
            <el-table-column prop="planDate" label="计划日期" width="110" />
            <el-table-column label="实收/实付" width="130" align="right">
              <template #default="{ row }">{{ row.actualAmount != null ? fmtMoney(row.actualAmount) : '—' }}</template>
            </el-table-column>
            <el-table-column prop="actualDate" label="实际日期" width="110" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'CONFIRMED' ? 'success' : (row.status === 'REVERSED' ? 'info' : 'warning')">
                  {{ row.statusLabel }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button v-if="contractList?.canManage && row.status === 'PLANNED'" size="small" text type="primary" @click="confirmPayment(row)">确认</el-button>
                <el-button v-if="contractList?.canManage && row.status === 'CONFIRMED'" size="small" text type="danger" @click="reversePayment(row)">红冲</el-button>
              </template>
            </el-table-column>
            <template #empty><div style="padding: 16px 0" class="hint">暂无收付款计划</div></template>
          </el-table>
        </el-dialog>

        <el-dialog v-model="payFormVisible" title="新增收付款计划" width="460px">
          <el-form label-width="90px" size="small">
            <el-form-item label="计划金额" required>
              <el-input-number v-model="payForm.planAmount" :min="0" :precision="2" style="width: 100%" />
            </el-form-item>
            <el-form-item label="计划日期">
              <el-date-picker v-model="payForm.planDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button size="small" @click="payFormVisible = false">取消</el-button>
            <el-button size="small" type="primary" :loading="savingPayment" @click="doAddPayment">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane label="数字人" name="ai">
        <!-- 已分配数字人：复用既有「数字员工」，不新建第二套 -->
        <el-card shadow="never" v-loading="workerLoading">
          <template #header>
            <div class="card-header">
              <span>已分配的数字员工（复用「数字员工」模块，不新建第二套）</span>
              <el-button v-if="workerList?.canManage" size="small" type="primary" @click="openAssign">分配数字人</el-button>
            </div>
          </template>
          <el-table :data="workers" size="small">
            <el-table-column label="数字员工" min-width="180">
              <template #default="{ row }">
                {{ row.name || `#${row.workerId}` }}
                <el-tag v-if="row.workerMissing" size="small" type="danger" effect="plain">已移除</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="120">
              <template #default="{ row }">{{ row.workerType || '—' }}</template>
            </el-table-column>
            <el-table-column label="本项目用途" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ row.assignRole || '—' }}</template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  :disabled="!workerList?.canManage"
                  @change="(v: boolean) => toggleWorker(row, v)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button v-if="workerList?.canManage" size="small" text type="danger" @click="removeWorker(row)">移除</el-button>
              </template>
            </el-table-column>
            <template #empty><div style="padding: 16px 0" class="hint">尚未分配数字人</div></template>
          </el-table>
        </el-card>

        <!-- 上下文来源：后台上传 / 网上搜索 / 政策 -->
        <el-card shadow="never" style="margin-top: 12px" v-loading="ctxLoading">
          <template #header>
            <div class="card-header">
              <span>项目上下文来源（后台上传 / 网上搜索 / 政策）</span>
              <el-button v-if="ctxList?.canManage" size="small" type="primary" @click="openCtx">新增来源</el-button>
            </div>
          </template>
          <el-table :data="ctxItems" size="small">
            <el-table-column label="来源" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.name }}</template>
            </el-table-column>
            <el-table-column label="类型" width="110">
              <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.typeLabel }}</el-tag></template>
            </el-table-column>
            <el-table-column label="作用范围" width="170" show-overflow-tooltip>
              <template #default="{ row }">{{ row.workerName }}</template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  :disabled="!ctxList?.canManage"
                  @change="(v: boolean) => toggleCtx(row, v)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button v-if="ctxList?.canManage" size="small" text type="danger" @click="removeCtx(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><div style="padding: 16px 0" class="hint">暂无上下文来源</div></template>
          </el-table>
          <p class="hint" style="margin: 10px 0 0">
            「项目级（全体数字人）」对已分配的全部数字人生效；关闭（停用）后保留配置但不参与上下文组装。
            移除数字员工时，其**专属**上下文来源会一并移除（项目级默认不受影响）。
          </p>
        </el-card>

        <!-- 生效预览：现在到底会给数字人喂什么上下文 -->
        <el-card shadow="never" style="margin-top: 12px">
          <template #header>
            <div class="card-header">
              <span>生效上下文预览</span>
              <el-select
                v-model="scopeWorkerId"
                size="small"
                clearable
                placeholder="选择数字人（留空看项目级默认）"
                style="width: 260px"
                @change="previewScope"
              >
                <el-option v-for="w in ctxList?.workers || []" :key="w.workerId" :label="w.name" :value="w.workerId" />
              </el-select>
            </div>
          </template>
          <div v-if="aiScope">
            共 <b>{{ aiScope.effectiveCount }}</b> 项生效：
            <el-tag v-for="s in aiScope.effective" :key="s.id" size="small" style="margin: 2px 4px 2px 0">
              {{ s.typeLabel }}·{{ s.name }}
            </el-tag>
            <span v-if="!aiScope.effectiveCount" class="hint">（当前没有启用的上下文来源）</span>
          </div>
          <div v-else class="hint">选择数字人后查看其实际生效的上下文。</div>
        </el-card>

        <!-- 分配数字人 -->
        <el-dialog v-model="assignVisible" title="分配数字人" width="520px">
          <el-form label-width="90px" size="small">
            <el-form-item label="数字员工" required>
              <el-select v-model="assignWorkerId" filterable placeholder="从既有数字员工中选择" style="width: 100%">
                <el-option
                  v-for="c in workerCandidates"
                  :key="c.workerId"
                  :label="c.status ? `${c.name}（${c.status}）` : c.name"
                  :value="c.workerId"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="本项目用途"><el-input v-model="assignRole" placeholder="如：项目助理 / 合同初审" /></el-form-item>
          </el-form>
          <p v-if="!workerCandidates.length" class="hint">暂无可分配的数字员工。请先在「数字员工」中创建并启用。</p>
          <template #footer>
            <el-button size="small" @click="assignVisible = false">取消</el-button>
            <el-button size="small" type="primary" :loading="savingWorker" :disabled="!assignWorkerId" @click="doAssign">分配</el-button>
          </template>
        </el-dialog>

        <!-- 新增上下文来源 -->
        <el-dialog v-model="ctxVisible" title="新增上下文来源" width="600px">
          <el-form label-width="100px" size="small">
            <el-form-item label="来源类型" required>
              <el-radio-group v-model="ctxForm.sourceType">
                <el-radio value="UPLOAD">后台上传</el-radio>
                <el-radio value="WEB_SEARCH">网上搜索</el-radio>
                <el-radio value="POLICY">政策</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="作用范围">
              <el-select v-model="ctxForm.workerId" style="width: 100%">
                <el-option label="项目级（全体数字人）" :value="0" />
                <el-option v-for="w in ctxList?.workers || []" :key="w.workerId" :label="w.name" :value="w.workerId" />
              </el-select>
            </el-form-item>

            <template v-if="ctxForm.sourceType === 'UPLOAD'">
              <el-form-item label="项目文件夹">
                <el-select v-model="ctxForm.folderId" clearable filterable placeholder="整目录纳入（可选）" style="width: 100%">
                  <el-option v-for="f in projectFolderOptions" :key="f.id" :label="f.label" :value="f.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="单个文件 id">
                <el-input-number v-model="ctxForm.fileId" :min="1" :controls="false" placeholder="sys_file.id（可选）" style="width: 100%" />
              </el-form-item>
              <p class="hint">目录与文件至少填一项（可只填目录）。</p>
            </template>

            <template v-else-if="ctxForm.sourceType === 'WEB_SEARCH'">
              <el-form-item label="搜索关键词" required>
                <el-input v-model="ctxForm.keywords" placeholder="多个关键词用逗号分隔，如：智慧城市,数据治理" />
              </el-form-item>
              <el-form-item label="限定域名">
                <el-input v-model="ctxForm.domains" placeholder="可选，逗号分隔，如：gov.cn,ndrc.gov.cn" />
              </el-form-item>
              <el-form-item label="最大条数">
                <el-input-number v-model="ctxForm.maxResults" :min="1" :max="100" />
              </el-form-item>
            </template>

            <template v-else>
              <el-form-item label="政策文档 id" required>
                <el-input-number v-model="ctxForm.kbDocumentId" :min="1" :controls="false" placeholder="kb_document.id" style="width: 100%" />
              </el-form-item>
            </template>

            <el-form-item label="显示名称">
              <el-input v-model="ctxForm.name" placeholder="留空则按来源自动生成" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button size="small" @click="ctxVisible = false">取消</el-button>
            <el-button size="small" type="primary" :loading="savingCtx" @click="saveCtx">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>

    <!-- ==================== 绑定仓库 ==================== -->
    <el-dialog v-model="bindVisible" title="绑定代码仓库" width="560px">
      <el-select v-model="bindRepoId" placeholder="选择尚未归属任何项目的仓库" filterable style="width: 100%">
        <el-option v-for="r in bindableRepos" :key="r.id" :label="repoLabel(r)" :value="r.id" />
      </el-select>
      <div class="hint" style="margin-top: 8px">仅显示状态为「可用」且尚未归属任何项目的仓库。</div>
      <template #footer>
        <el-button size="small" @click="bindVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="binding" @click="doBind">绑定</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 新建/编辑任务 ==================== -->
    <el-dialog v-model="taskVisible" :title="taskForm.id ? '编辑任务' : '新建任务'" width="640px">
      <el-form :model="taskForm" label-width="110px" size="small">
        <el-form-item label="任务标题" required>
          <el-input v-model="taskForm.title" placeholder="请输入任务标题" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="taskForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="taskForm.assigneeMemberId" clearable filterable placeholder="选择本项目成员" style="width: 100%">
            <el-option v-for="m in members" :key="m.memberId" :label="m.name || String(m.memberId)" :value="m.memberId" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="taskForm.priority" style="width: 160px">
            <el-option v-for="p in PM_TASK_PRIORITIES" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="起止日期">
          <el-date-picker
            v-model="taskDateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="截止"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="进度">
          <el-input-number v-model="taskForm.progress" :min="0" :max="100" />
        </el-form-item>

        <!-- ============ 仓库关联：仅开发项目渲染（业务项目连字段都不出现） ============ -->
        <template v-if="isDev">
          <el-divider content-position="left">代码仓库关联（仅开发项目）</el-divider>
          <el-form-item label="关联仓库">
            <el-select v-model="taskForm.repoId" clearable placeholder="选择本项目已绑定的仓库" style="width: 100%">
              <el-option v-for="r in boundRepos" :key="r.id" :label="repoLabel(r)" :value="r.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="Issue 号">
            <el-input v-model="taskForm.repoIssueNo" placeholder="选择仓库后必填，如 #12 或 12" />
          </el-form-item>
          <el-form-item label="分支">
            <el-input v-model="taskForm.repoBranch" placeholder="选填，如 feature/login" />
          </el-form-item>
          <el-form-item label="提交 SHA">
            <el-input v-model="taskForm.repoCommitSha" placeholder="选填" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button size="small" @click="taskVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="savingTask" @click="saveTask">保存</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 添加成员 ==================== -->
    <el-dialog v-model="memberVisible" title="添加项目成员" width="560px">
      <el-form label-width="90px" size="small">
        <el-form-item label="员工">
          <el-select v-model="newMemberId" filterable placeholder="从本企业在册员工中选择" style="width: 100%">
            <el-option
              v-for="c in candidates"
              :key="c.memberId"
              :label="`${c.name || c.memberId}${c.employeeNo ? '（' + c.employeeNo + '）' : ''}`"
              :value="c.memberId"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="项目角色">
          <el-select v-model="newMemberRole" style="width: 100%">
            <el-option v-for="r in memberList?.roleOptions || []" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="memberVisible = false">取消</el-button>
        <el-button size="small" type="primary" :loading="savingMember" @click="doAddMember">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  pmProjectDetail, pmChangeProjectStatus, pmBoundRepos, pmBindableRepos, pmBindRepo, pmUnbindRepo,
  pmTasks, pmCreateTask, pmUpdateTask, pmChangeTaskStatus, pmDeleteTask,
  pmMembers, pmMemberCandidates, pmAddMember, pmChangeMemberRole, pmRemoveMember, pmErrMsg,
  // 文档（批次 3 / docs/43）：企业级公共（只读挂载）与项目专属（可写）同树呈现
  pmDocTree, pmCreateFolder, pmDeleteFolder, pmCreateDocument, pmDocDetail, pmDeleteDocument,
  // 经费 / 合同（批次 4 / docs/43 §4）：经费为追加式账目（无修改端点），合同确认收付款自动生成流水（BR-09）
  pmExpenses, pmCreateExpense, pmReverseExpense,
  pmContracts, pmCreateContract, pmUpdateContract, pmChangeContractStatus,
  pmContractPayments, pmAddContractPayment, pmConfirmContractPayment, pmReverseContractPayment,
  // 数字人 + 上下文（V74/V76 / docs/43 §5）：数字人=既有「数字员工」，上下文三类来源同表
  pmWorkers, pmAssignWorker, pmUpdateWorker, pmUnassignWorker,
  pmContextSources, pmCreateContextSource, pmDeleteContextSource, pmUpdateContextSource, pmAiScope,
  type PmProject, type PmRepo, type PmTask, type PmTaskList, type PmMember, type PmMemberList,
  type PmMemberCandidate, type PmDocTree, type PmDocNode, type PmDocItem,
  type PmExpenseList, type PmExpenseItem, type PmContractList, type PmContractItem, type PmContractPaymentItem,
  type PmWorkerList, type PmWorkerItem, type PmWorkerCandidate,
  type PmContextSourceList, type PmContextSourceItem, type PmAiScope
} from '@/api/pm'
import {
  PM_PROJECT_TYPE_LABEL, PM_PROJECT_STATUS, PM_PROJECT_STATUS_LABEL, PM_PROJECT_STATUS_TAG,
  PM_PROJECT_ROLE_LABEL, PM_TASK_STATUS, PM_TASK_STATUS_LABEL, PM_TASK_STATUS_TAG,
  PM_TASK_PRIORITIES, PM_TASK_PRIORITY_LABEL, PM_REPO_SYNC_STATUS_LABEL,
  // 仓库状态文案与 el-tag 类型复用仓库模块那一份常量（单一判定点），
  // 不要在这里另写一套「创建中/可用/失败」映射 —— 两处口径必漂移。
  GITEE_PROJECT_STATUS_LABEL, GITEE_PROJECT_STATUS_TAG
} from '@/constants/permissions'
// 重试建仓：仓库的写入动作仍由仓库模块的接口负责（PM 只是入口，不复制业务规则）。
import { giteeRetryProject, giteeErrMsg, giteeConfig } from '@/api/gitee'
// 文档上传复用既有通用上传接口（POST /api/v1/files/upload），不另造上传通道。
import { uploadFile } from '@/api/resource'

const route = useRoute()
const router = useRouter()
const projectId = Number(route.params.id)

const loading = ref(false)
const tab = ref('overview')
const project = ref<PmProject | null>(null)
const newStatus = ref('')

const boundRepos = ref<PmRepo[]>([])
const bindableRepos = ref<PmRepo[]>([])
const bindVisible = ref(false)
const bindRepoId = ref<number>()
const binding = ref(false)

// 仓库治理提示：Webhook 回调地址是否已配置（来自 /gitee/config，单一事实源）。
// null = 未取到（不显示提示），避免把「接口不可达」误报成「配置缺失」。
const webhookBaseUrlOk = ref<boolean | null>(null)
const giteeProviderLabel = ref('Gitee')
const giteeConfigKey = ref('aioa.gitee')

const taskList = ref<PmTaskList | null>(null)
const tasks = ref<PmTask[]>([])
const taskVisible = ref(false)
const savingTask = ref(false)
const taskDateRange = ref<[string, string] | null>(null)
const taskForm = reactive<{
  id?: number; title: string; description: string; priority: string
  assigneeMemberId?: number | null; progress: number
  repoId?: number | null; repoIssueNo?: string; repoBranch?: string; repoCommitSha?: string
}>({
  title: '', description: '', priority: 'MEDIUM', assigneeMemberId: null, progress: 0
})

const memberList = ref<PmMemberList | null>(null)
const members = ref<PmMember[]>([])
const candidates = ref<PmMemberCandidate[]>([])
const memberVisible = ref(false)
const savingMember = ref(false)
const newMemberId = ref<number>()
const newMemberRole = ref('MEMBER')

/**
 * 类型是页面所有「配置面」的唯一开关。
 *
 * <p>业务项目：不渲染「代码仓库」页签、不渲染任务的仓库列与仓库关联表单。
 * 后端同样是这个口径（{@code ProjectTypeGuard}），前端隐藏不是安全边界。</p>
 */
const isDev = computed(() => project.value?.projectType === 'DEV')

function fmtMoney(v?: number | string) {
  if (v === undefined || v === null || v === '') return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
}

function memberName(memberId?: number | null) {
  if (!memberId) return '—'
  return members.value.find((m) => m.memberId === memberId)?.name || String(memberId)
}

function repoLabel(r: PmRepo) {
  const path = [r.gitee_owner, r.gitee_repo].filter(Boolean).join('/')
  return r.name ? `${r.name}${path ? `（${path}）` : ''}` : (r.repo_name || String(r.id))
}

async function loadAll() {
  loading.value = true
  try {
    project.value = await pmProjectDetail(projectId)
    newStatus.value = project.value.status
    await Promise.all([loadRepos(), loadMembers(), loadTasks()])
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载项目详情失败'))
  } finally {
    loading.value = false
  }
}

async function loadRepos() {
  if (!isDev.value) {
    boundRepos.value = []
    return
  }
  // Webhook 回调地址是否已配置：决定仓库是否可能停在「未就绪」。取不到就置 null（不显示提示），
  // 不能用 `false` 兜底 —— 那会把「接口不可达」误报成「配置缺失」。
  try {
    const cfg = await giteeConfig()
    webhookBaseUrlOk.value = cfg.webhookBaseUrlConfigured
    giteeProviderLabel.value = cfg.providerLabel || 'Gitee'
    giteeConfigKey.value = cfg.configKey || 'aioa.gitee'
  } catch {
    webhookBaseUrlOk.value = null
  }
  try {
    boundRepos.value = await pmBoundRepos(projectId)
  } catch (e) {
    boundRepos.value = []
    ElMessage.warning(pmErrMsg(e, '加载已绑仓库失败'))
  }
}

async function loadTasks() {
  try {
    const res = await pmTasks(projectId)
    taskList.value = res
    tasks.value = res.items
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载任务失败'))
  }
}

async function loadMembers() {
  try {
    const res = await pmMembers(projectId)
    memberList.value = res
    members.value = res.items
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载成员失败'))
  }
}

async function changeStatus() {
  if (!newStatus.value) return
  try {
    project.value = await pmChangeProjectStatus(projectId, newStatus.value)
    ElMessage.success('状态已更新')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '变更状态失败'))
  }
}

// ---------------------------------------------------------------- 仓库
async function openBind() {
  bindVisible.value = true
  bindRepoId.value = undefined
  try {
    bindableRepos.value = await pmBindableRepos(projectId)
  } catch (e) {
    bindableRepos.value = []
    ElMessage.warning(pmErrMsg(e, '加载可绑定仓库失败'))
  }
}

async function doBind() {
  if (!bindRepoId.value) {
    ElMessage.warning('请选择要绑定的仓库')
    return
  }
  binding.value = true
  try {
    const res = await pmBindRepo(projectId, bindRepoId.value)
    boundRepos.value = res.boundRepos
    bindVisible.value = false
    ElMessage.success('仓库已绑定')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '绑定失败'))
  } finally {
    binding.value = false
  }
}

async function unbind(row: PmRepo) {
  try {
    await ElMessageBox.confirm(`确认解绑仓库「${repoLabel(row)}」？仅解除与本项目的关联，不删除仓库。`, '解绑仓库', { type: 'warning' })
  } catch {
    return
  }
  try {
    const res = await pmUnbindRepo(projectId, row.id)
    boundRepos.value = res.boundRepos
    ElMessage.success('已解绑')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '解绑失败'))
  }
}

/**
 * 重试建仓（仅非 ACTIVE 的行显示入口）。
 *
 * <p>为什么放在这里：建仓是**异步任务**（`gitee_task`），用户看到「创建失败」后，
 * 修好前置条件（补归属部门 / 完成企业初始化）总得有个地方让它再跑一次 ——
 * 原先那个入口只在「项目与仓库」页，现在仓库跟着开发项目走，入口也必须跟过来，
 * 否则用户会被指到一个已从菜单撤掉的页面。</p>
 */
async function retryRepo(row: PmRepo) {
  try {
    await giteeRetryProject(row.id)
    ElMessage.success('已重新排入建仓任务，稍后刷新查看状态')
    await loadRepos()
  } catch (e) {
    ElMessage.error(giteeErrMsg(e, '重试建仓失败'))
  }
}

// ---------------------------------------------------------------- 任务
function openTask(row?: PmTask) {
  if (row) {
    Object.assign(taskForm, {
      id: row.id, title: row.title, description: row.description || '', priority: row.priority || 'MEDIUM',
      assigneeMemberId: row.assigneeMemberId ?? null, progress: row.progress ?? 0,
      repoId: row.repoId ?? null, repoIssueNo: row.repoIssueNo || '', repoBranch: row.repoBranch || '',
      repoCommitSha: row.repoCommitSha || ''
    })
    taskDateRange.value = row.startDate && row.dueDate ? [row.startDate, row.dueDate] : null
  } else {
    Object.assign(taskForm, {
      id: undefined, title: '', description: '', priority: 'MEDIUM', assigneeMemberId: null,
      progress: 0, repoId: null, repoIssueNo: '', repoBranch: '', repoCommitSha: ''
    })
    taskDateRange.value = null
  }
  taskVisible.value = true
}

async function saveTask() {
  if (!taskForm.title.trim()) {
    ElMessage.warning('请填写任务标题')
    return
  }
  const body = {
    title: taskForm.title.trim(),
    description: taskForm.description,
    priority: taskForm.priority,
    assigneeMemberId: taskForm.assigneeMemberId ?? null,
    progress: taskForm.progress,
    startDate: taskDateRange.value?.[0] ?? null,
    dueDate: taskDateRange.value?.[1] ?? null,
    // 业务项目不发仓库字段（后端 BR-01/BR-12 会拒；不发即不制造注定失败的请求）
    repoId: isDev.value ? (taskForm.repoId ?? null) : undefined,
    repoIssueNo: isDev.value ? (taskForm.repoIssueNo || null) : undefined,
    repoBranch: isDev.value ? (taskForm.repoBranch || null) : undefined,
    repoCommitSha: isDev.value ? (taskForm.repoCommitSha || null) : undefined
  }
  savingTask.value = true
  try {
    if (taskForm.id) {
      await pmUpdateTask(projectId, taskForm.id, body)
    } else {
      await pmCreateTask(projectId, body)
    }
    taskVisible.value = false
    ElMessage.success('已保存')
    loadTasks()
  } catch (e) {
    // 状态机 / 成对约束 / 仓库绑定校验的原文都在这里展示
    ElMessage.error(pmErrMsg(e, '保存任务失败'))
  } finally {
    savingTask.value = false
  }
}

async function changeTaskStatus(row: PmTask, status: string) {
  if (status === row.status) return
  try {
    await pmChangeTaskStatus(projectId, row.id, status)
    ElMessage.success('状态已更新')
    loadTasks()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '变更状态失败'))
    loadTasks()
  }
}

async function removeTask(row: PmTask) {
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.title}」？`, '删除任务', { type: 'warning' })
  } catch {
    return
  }
  try {
    await pmDeleteTask(projectId, row.id)
    ElMessage.success('已删除')
    loadTasks()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '删除失败'))
  }
}

// ---------------------------------------------------------------- 成员
async function openAddMember() {
  memberVisible.value = true
  newMemberId.value = undefined
  newMemberRole.value = 'MEMBER'
  try {
    candidates.value = await pmMemberCandidates(projectId)
  } catch (e) {
    candidates.value = []
    ElMessage.warning(pmErrMsg(e, '加载员工候选失败'))
  }
}

async function doAddMember() {
  if (!newMemberId.value) {
    ElMessage.warning('请选择员工')
    return
  }
  savingMember.value = true
  try {
    const res = await pmAddMember(projectId, newMemberId.value, newMemberRole.value)
    memberList.value = res
    members.value = res.items
    memberVisible.value = false
    ElMessage.success('已添加')
    loadTasks()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '添加成员失败'))
  } finally {
    savingMember.value = false
  }
}

async function changeMemberRole(row: PmMember, roleCode: string) {
  if (roleCode === row.roleCode) return
  try {
    const res = await pmChangeMemberRole(projectId, row.id, roleCode)
    memberList.value = res
    members.value = res.items
    ElMessage.success('角色已更新')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '变更角色失败'))
    loadMembers()
  }
}

async function removeMember(row: PmMember) {
  try {
    await ElMessageBox.confirm(`确认将「${row.name}」移出本项目？`, '移除成员', { type: 'warning' })
  } catch {
    return
  }
  try {
    const res = await pmRemoveMember(projectId, row.id)
    memberList.value = res
    members.value = res.items
    ElMessage.success('已移除')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '移除失败'))
  }
}

/* ==================== 文档（批次 3 / docs/43） ==================== */

const docTree = ref<PmDocTree | null>(null)
const docLoading = ref(false)
const selectedDocKey = ref('')
const selectedDocName = ref('')
const selectedDocReadonly = ref(false)
const selectedFolderId = ref<number | null>(null)
const selectedDocs = ref<PmDocItem[]>([])
const newFolderVisible = ref(false)
const newFolderName = ref('')
const aiDocVisible = ref(false)
const aiDocForm = reactive({ name: '', contentText: '' })
const docPreviewVisible = ref(false)
const docPreview = ref<PmDocItem | null>(null)
const savingDoc = ref(false)
const uploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

interface DocTreeNode {
  key: string
  label: string
  folderId: number | null
  readonly: boolean
  docs: PmDocItem[]
  children: DocTreeNode[]
}

/** 企业级公共（只读挂载）与项目专属同树呈现；写操作只在项目专属下出现。 */
const docTreeData = computed<DocTreeNode[]>(() => {
  const mk = (n: PmDocNode): DocTreeNode => ({
    key: `f${n.id}`,
    label: n.name,
    folderId: n.id,
    readonly: n.readonly,
    docs: n.documents || [],
    children: (n.children || []).map(mk)
  })
  const nodes: DocTreeNode[] = []
  const ent = docTree.value?.enterprise || []
  nodes.push({
    key: 'ent-root',
    label: docTree.value?.enterpriseRootLabel || '企业级公共文件夹',
    folderId: null,
    readonly: true,
    docs: [],
    children: ent.map(mk)
  })
  ;(docTree.value?.project || []).forEach((r) => nodes.push(mk(r)))
  return nodes
})

function projectRootId(): number | null {
  const roots = docTree.value?.project || []
  return roots.length ? roots[0].id : null
}

function onDocNodeClick(data: DocTreeNode) {
  selectedDocKey.value = data.key
  selectedDocName.value = data.label
  selectedDocReadonly.value = !!data.readonly
  selectedFolderId.value = data.folderId ?? null
  selectedDocs.value = data.docs || []
}

async function loadDocTree() {
  docLoading.value = true
  try {
    docTree.value = await pmDocTree(projectId)
    const roots = docTree.value.project || []
    if (roots.length) {
      onDocNodeClick({
        key: `f${roots[0].id}`,
        label: roots[0].name,
        folderId: roots[0].id,
        readonly: false,
        docs: roots[0].documents || [],
        children: []
      })
    }
  } catch (e) {
    ElMessage.error(pmErrMsg(e))
  } finally {
    docLoading.value = false
  }
}

function triggerUpload() {
  if (!selectedFolderId.value) {
    ElMessage.warning('请先选择一个项目文件夹再上传')
    return
  }
  fileInputRef.value?.click()
}

async function onFilePicked(ev: Event) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  if (!selectedFolderId.value) {
    ElMessage.warning('请先选择一个项目文件夹再上传')
    input.value = ''
    return
  }
  uploading.value = true
  try {
    const up = await uploadFile(f)
    await pmCreateDocument(projectId, {
      folderId: selectedFolderId.value,
      name: f.name,
      source: 'UPLOAD',
      fileId: up.id,
      // 后端在缺省时会自行从 sys_file.size 取；这里带上保持两端口径一致。
      sizeBytes: f.size
    })
    ElMessage.success('已上传')
    await loadDocTree()
  } catch (e) {
    ElMessage.error(pmErrMsg(e))
  } finally {
    uploading.value = false
    input.value = ''
  }
}

async function doCreateFolder() {
  const name = newFolderName.value.trim()
  if (!name) {
    ElMessage.warning('请填写文件夹名称')
    return
  }
  const parentId = selectedFolderId.value && !selectedDocReadonly.value ? selectedFolderId.value : projectRootId()
  if (!parentId) {
    ElMessage.warning('项目根目录不存在，请刷新')
    return
  }
  savingDoc.value = true
  try {
    await pmCreateFolder(projectId, { name, parentId })
    ElMessage.success('已创建')
    newFolderVisible.value = false
    newFolderName.value = ''
    await loadDocTree()
  } catch (e) {
    ElMessage.error(pmErrMsg(e))
  } finally {
    savingDoc.value = false
  }
}

async function doCreateAiDoc() {
  if (!selectedFolderId.value || selectedDocReadonly.value) {
    ElMessage.warning('请先选择一个项目文件夹')
    return
  }
  if (!aiDocForm.name.trim()) {
    ElMessage.warning('请填写文档名称')
    return
  }
  if (!aiDocForm.contentText.trim()) {
    ElMessage.warning('请填写正文')
    return
  }
  savingDoc.value = true
  try {
    await pmCreateDocument(projectId, {
      folderId: selectedFolderId.value,
      name: aiDocForm.name.trim(),
      source: 'AI',
      contentText: aiDocForm.contentText
    })
    ElMessage.success('已创建')
    aiDocVisible.value = false
    aiDocForm.name = ''
    aiDocForm.contentText = ''
    await loadDocTree()
  } catch (e) {
    ElMessage.error(pmErrMsg(e))
  } finally {
    savingDoc.value = false
  }
}

async function previewDoc(row: PmDocItem) {
  docPreview.value = row
  docPreviewVisible.value = true
  try {
    docPreview.value = await pmDocDetail(projectId, row.id)
  } catch (e) {
    ElMessage.error(pmErrMsg(e))
  }
}

async function removeDoc(row: PmDocItem) {
  try {
    await ElMessageBox.confirm(`确定删除文档「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await pmDeleteDocument(projectId, row.id)
    ElMessage.success('已删除')
    await loadDocTree()
  } catch (e) {
    ElMessage.error(pmErrMsg(e))
  }
}

/* ==================== 经费（批次 4 / docs/43 §4） ====================
 * 追加式账目：页面**只有**「追加」和「红冲」，没有编辑/删除 —— 与后端一致（无 PUT/DELETE 端点）。
 * 不要在这里加「编辑流水」按钮：那会造出一个后端必然 404/405 的假入口。 */

const expenseList = ref<PmExpenseList | null>(null)
const expenses = ref<PmExpenseItem[]>([])
const expenseLoading = ref(false)
const expenseFilter = reactive({ direction: '', category: '' })
const expenseVisible = ref(false)
const savingExpense = ref(false)
const expenseForm = reactive<{
  direction: 'IN' | 'OUT'; category: string; amount: number
  occurredAt: string; allocRatio?: number; remark: string
}>({ direction: 'OUT', category: 'OTHER', amount: 0, occurredAt: '', allocRatio: undefined, remark: '' })

async function loadExpenses() {
  expenseLoading.value = true
  try {
    const res = await pmExpenses(projectId, {
      direction: expenseFilter.direction || undefined,
      category: expenseFilter.category || undefined
    })
    expenseList.value = res
    expenses.value = res.items
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载经费失败'))
  } finally {
    expenseLoading.value = false
  }
}

function openExpense() {
  Object.assign(expenseForm, { direction: 'OUT', category: 'OTHER', amount: 0, occurredAt: '', allocRatio: undefined, remark: '' })
  expenseVisible.value = true
}

async function saveExpense() {
  if (!expenseForm.category) {
    ElMessage.warning('请选择费用分类')
    return
  }
  savingExpense.value = true
  try {
    await pmCreateExpense(projectId, {
      direction: expenseForm.direction,
      category: expenseForm.category,
      amount: expenseForm.amount,
      occurredAt: expenseForm.occurredAt || undefined,
      allocRatio: expenseForm.allocRatio ?? undefined,
      remark: expenseForm.remark || undefined
    })
    expenseVisible.value = false
    ElMessage.success('已追加')
    await loadExpenses()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '保存失败'))
  } finally {
    savingExpense.value = false
  }
}

async function reverseExpense(row: PmExpenseItem) {
  let reason = ''
  try {
    const r = await ElMessageBox.prompt('红冲原因（可选，将记入红冲行摘要）', `红冲流水 ${fmtMoney(row.amount)}`, {
      inputPlaceholder: '如：录入金额有误',
      confirmButtonText: '确认红冲',
      cancelButtonText: '取消'
    })
    reason = String(r.value || '')
  } catch {
    return
  }
  try {
    await pmReverseExpense(projectId, row.id, reason || undefined)
    ElMessage.success('已红冲（原行保留，新增反向流水）')
    await loadExpenses()
  } catch (e) {
    // 重复红冲 → 后端 409，原文展示
    ElMessage.error(pmErrMsg(e, '红冲失败'))
  }
}

/* ==================== 合同 + 收付款（批次 4 / docs/43 §4） ==================== */

const contractList = ref<PmContractList | null>(null)
const contracts = ref<PmContractItem[]>([])
const contractLoading = ref(false)
const contractFilter = reactive({ direction: '' })
const contractVisible = ref(false)
const savingContract = ref(false)
const contractForm = reactive<{
  id?: number; contractNo: string; name: string; direction: 'IN' | 'OUT'
  partyName: string; amount: number; signedAt: string
}>({ contractNo: '', name: '', direction: 'OUT', partyName: '', amount: 0, signedAt: '' })

const payVisible = ref(false)
const payFormVisible = ref(false)
const savingPayment = ref(false)
const currentContract = ref<PmContractItem | null>(null)
const payments = ref<PmContractPaymentItem[]>([])
const payForm = reactive({ planAmount: 0, planDate: '' })

async function loadContracts() {
  contractLoading.value = true
  try {
    const res = await pmContracts(projectId, { direction: contractFilter.direction || undefined })
    contractList.value = res
    contracts.value = res.items
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载合同失败'))
  } finally {
    contractLoading.value = false
  }
}

function openContract(row?: PmContractItem) {
  if (row) {
    Object.assign(contractForm, {
      id: row.id, contractNo: row.contractNo, name: row.name, direction: row.direction,
      partyName: row.partyName || '', amount: Number(row.amount) || 0, signedAt: row.signedAt || ''
    })
  } else {
    Object.assign(contractForm, {
      id: undefined, contractNo: '', name: '', direction: 'OUT', partyName: '', amount: 0, signedAt: ''
    })
  }
  contractVisible.value = true
}

async function saveContract() {
  if (!contractForm.name.trim()) {
    ElMessage.warning('请填写合同名称')
    return
  }
  if (!contractForm.id && !contractForm.contractNo.trim()) {
    ElMessage.warning('请填写合同编号')
    return
  }
  savingContract.value = true
  try {
    if (contractForm.id) {
      await pmUpdateContract(projectId, contractForm.id, {
        name: contractForm.name.trim(),
        partyName: contractForm.partyName || undefined,
        amount: contractForm.amount,
        signedAt: contractForm.signedAt || undefined
      })
    } else {
      await pmCreateContract(projectId, {
        contractNo: contractForm.contractNo.trim(),
        name: contractForm.name.trim(),
        direction: contractForm.direction,
        partyName: contractForm.partyName || undefined,
        amount: contractForm.amount,
        signedAt: contractForm.signedAt || undefined
      })
    }
    contractVisible.value = false
    ElMessage.success('已保存')
    await loadContracts()
  } catch (e) {
    // 编号重复（409）/ 已结不可改（409）原文展示
    ElMessage.error(pmErrMsg(e, '保存失败'))
  } finally {
    savingContract.value = false
  }
}

async function changeContractStatus(row: PmContractItem, status: string) {
  if (status === row.status) return
  try {
    await pmChangeContractStatus(projectId, row.id, status)
    ElMessage.success('状态已更新')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '变更状态失败'))
  } finally {
    await loadContracts()
  }
}

async function openPayments(row: PmContractItem) {
  currentContract.value = row
  payVisible.value = true
  await loadPayments()
}

async function loadPayments() {
  if (!currentContract.value) return
  try {
    const res = await pmContractPayments(projectId, currentContract.value.id)
    payments.value = res.items
    currentContract.value = res.contract
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载收付款失败'))
  }
}

function openAddPayment() {
  payForm.planAmount = 0
  payForm.planDate = ''
  payFormVisible.value = true
}

async function doAddPayment() {
  if (!currentContract.value) return
  savingPayment.value = true
  try {
    await pmAddContractPayment(projectId, currentContract.value.id, {
      planAmount: payForm.planAmount,
      planDate: payForm.planDate || undefined
    })
    payFormVisible.value = false
    ElMessage.success('已新增期次')
    await loadPayments()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '新增失败'))
  } finally {
    savingPayment.value = false
  }
}

/**
 * 确认实收/实付 —— BR-09：后端同事务自动生成经费流水，前端**不再**另行登记。
 * 成功后同时刷新经费页（若已加载），让用户立刻看到自动入库的那条流水。
 */
async function confirmPayment(row: PmContractPaymentItem) {
  if (!currentContract.value) return
  try {
    await ElMessageBox.confirm(
      `确认第 ${row.seq} 期实收/实付 ${fmtMoney(row.planAmount)}？系统将自动生成一条经费流水。`,
      '确认收付款',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await pmConfirmContractPayment(projectId, currentContract.value.id, row.id, {})
    ElMessage.success('已确认，已自动生成经费流水')
    await loadPayments()
    if (expenseList.value) await loadExpenses()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '确认失败'))
    await loadPayments()
  }
}

async function reversePayment(row: PmContractPaymentItem) {
  if (!currentContract.value) return
  let reason = ''
  try {
    const r = await ElMessageBox.prompt('红冲原因（可选）', `红冲第 ${row.seq} 期收付款`, {
      inputPlaceholder: '如：款项退回',
      confirmButtonText: '确认红冲',
      cancelButtonText: '取消'
    })
    reason = String(r.value || '')
  } catch {
    return
  }
  try {
    await pmReverseContractPayment(projectId, currentContract.value.id, row.id, reason || undefined)
    ElMessage.success('已红冲（追加反向流水）')
    await loadPayments()
    if (expenseList.value) await loadExpenses()
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '红冲失败'))
  }
}

/* ==================== 数字人 + 上下文（V74/V76 / docs/43 §5） ====================
 * 「分配项目数字人」= 把**既有**数字员工（agent_worker）挂到项目，不新建第二套（docs/43 A3）。
 * 「项目上下文控制」= 维护该数字人在本项目可用的知识来源（上传/网搜/政策）+ 启停 + 生效预览。 */

const workerList = ref<PmWorkerList | null>(null)
const workers = ref<PmWorkerItem[]>([])
const workerCandidates = ref<PmWorkerCandidate[]>([])
const workerLoading = ref(false)
const assignVisible = ref(false)
const assignWorkerId = ref<number>()
const assignRole = ref('')
const savingWorker = ref(false)

const ctxList = ref<PmContextSourceList | null>(null)
const ctxItems = ref<PmContextSourceItem[]>([])
const ctxLoading = ref(false)
const ctxVisible = ref(false)
const savingCtx = ref(false)
const scopeWorkerId = ref<number>()
const aiScope = ref<PmAiScope | null>(null)

const ctxForm = reactive<{
  sourceType: 'UPLOAD' | 'WEB_SEARCH' | 'POLICY'
  workerId: number
  folderId?: number
  fileId?: number
  kbDocumentId?: number
  keywords: string
  domains: string
  maxResults: number
  name: string
}>({
  sourceType: 'UPLOAD',
  workerId: 0,
  keywords: '',
  domains: '',
  maxResults: 10,
  name: ''
})

/** UPLOAD 可选的项目文件夹（docTree.project 扁平化；只列项目专属，企业级是只读挂载不纳入上下文写）。 */
const projectFolderOptions = computed<Array<{ id: number; label: string }>>(() => {
  const out: Array<{ id: number; label: string }> = []
  const walk = (nodes: PmDocNode[], prefix: string) => {
    nodes.forEach((n) => {
      out.push({ id: n.id, label: `${prefix}${n.name}` })
      if (n.children?.length) walk(n.children, `${prefix}${n.name} / `)
    })
  }
  walk(docTree.value?.project || [], '')
  return out
})

async function loadWorkers() {
  workerLoading.value = true
  try {
    const res = await pmWorkers(projectId)
    workerList.value = res
    workers.value = res.items
    workerCandidates.value = res.candidates
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载数字人失败'))
  } finally {
    workerLoading.value = false
  }
}

async function loadContext() {
  ctxLoading.value = true
  try {
    const res = await pmContextSources(projectId)
    ctxList.value = res
    ctxItems.value = res.items
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载上下文来源失败'))
  } finally {
    ctxLoading.value = false
  }
}

function openAssign() {
  assignWorkerId.value = undefined
  assignRole.value = ''
  assignVisible.value = true
}

async function doAssign() {
  if (!assignWorkerId.value) {
    ElMessage.warning('请选择数字员工')
    return
  }
  savingWorker.value = true
  try {
    await pmAssignWorker(projectId, { workerId: assignWorkerId.value, assignRole: assignRole.value.trim() || undefined })
    ElMessage.success('已分配')
    assignVisible.value = false
    await Promise.all([loadWorkers(), loadContext()])
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '分配失败'))
  } finally {
    savingWorker.value = false
  }
}

async function toggleWorker(row: PmWorkerItem, enabled: boolean) {
  try {
    await pmUpdateWorker(projectId, row.id, { enabled })
    ElMessage.success(enabled ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '更新失败'))
  } finally {
    await loadWorkers()
  }
}

async function removeWorker(row: PmWorkerItem) {
  try {
    await ElMessageBox.confirm(
      `确定移除数字人「${row.name || ('#' + row.workerId)}」？其在本项目的专属上下文来源会一并移除。`,
      '提示',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const r = await pmUnassignWorker(projectId, row.id)
    ElMessage.success(r.removedContextSources ? `已移除（连带删除 ${r.removedContextSources} 项专属上下文）` : '已移除')
    await Promise.all([loadWorkers(), loadContext()])
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '移除失败'))
  }
}

async function openCtx() {
  ctxForm.sourceType = 'UPLOAD'
  ctxForm.workerId = 0
  ctxForm.folderId = undefined
  ctxForm.fileId = undefined
  ctxForm.kbDocumentId = undefined
  ctxForm.keywords = ''
  ctxForm.domains = ''
  ctxForm.maxResults = 10
  ctxForm.name = ''
  // 文件夹选择需要 docTree；未加载则先取一次
  if (!docTree.value) await loadDocTree()
  ctxVisible.value = true
}

async function saveCtx() {
  const body: Parameters<typeof pmCreateContextSource>[1] = { sourceType: ctxForm.sourceType, workerId: ctxForm.workerId }
  if (ctxForm.name.trim()) body.name = ctxForm.name.trim()
  if (ctxForm.sourceType === 'UPLOAD') {
    if (ctxForm.folderId) body.folderId = ctxForm.folderId
    if (ctxForm.fileId) body.fileId = ctxForm.fileId
    if (!body.folderId && !body.fileId) {
      ElMessage.warning('后台上传来源需选择目录或填写文件 id')
      return
    }
  } else if (ctxForm.sourceType === 'WEB_SEARCH') {
    const keywords = ctxForm.keywords.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    if (!keywords.length) {
      ElMessage.warning('请填写至少一个搜索关键词')
      return
    }
    body.config = {
      keywords,
      domains: ctxForm.domains.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
      maxResults: ctxForm.maxResults
    }
  } else {
    if (!ctxForm.kbDocumentId) {
      ElMessage.warning('请填写政策文档 id')
      return
    }
    body.kbDocumentId = ctxForm.kbDocumentId
  }
  savingCtx.value = true
  try {
    await pmCreateContextSource(projectId, body)
    ElMessage.success('已新增')
    ctxVisible.value = false
    await Promise.all([loadContext(), previewScope()])
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '新增失败'))
  } finally {
    savingCtx.value = false
  }
}

async function toggleCtx(row: PmContextSourceItem, enabled: boolean) {
  try {
    await pmUpdateContextSource(projectId, row.id, { enabled })
    ElMessage.success(enabled ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '更新失败'))
  } finally {
    await Promise.all([loadContext(), previewScope()])
  }
}

async function removeCtx(row: PmContextSourceItem) {
  try {
    await ElMessageBox.confirm(`确定删除上下文来源「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await pmDeleteContextSource(projectId, row.id)
    ElMessage.success('已删除')
    await Promise.all([loadContext(), previewScope()])
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '删除失败'))
  }
}

async function previewScope() {
  try {
    aiScope.value = await pmAiScope(projectId, scopeWorkerId.value)
  } catch (e) {
    ElMessage.error(pmErrMsg(e, '加载生效上下文失败'))
  }
}

watch(tab, (v) => {
  if (v === 'docs' && !docTree.value) loadDocTree()
  else if (v === 'expenses' && !expenseList.value) loadExpenses()
  else if (v === 'contracts' && !contractList.value) loadContracts()
  else if (v === 'ai' && !workerList.value) {
    loadWorkers()
    loadContext()
  }
})

onMounted(loadAll)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.desc {
  margin: 12px 0 0;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.6;
}
/* 建仓/配置 Webhook 的失败原因：后端回的是给人读的整句（含「怎么补救」）。
   用 danger 色是因为这一列**只在失败行**才可能有值（成功行显示「—」），
   属于需要用户处理的异常态；允许换行，避免长句撑破表格。 */
.repo-error {
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}
/* 经费金额：收入/支出取色。按中国财务阅读习惯，红色=支出（流出）、绿色=收入（流入）——
   与股票涨跌配色无关，这里跟随「支出为负向」的通用财务配色，避免用户误读。 */
.money-in {
  color: var(--el-color-success);
}
.money-out {
  color: var(--el-color-danger);
}
</style>
