<template>
  <!-- 无效 ID：报错并跳转，渲染空白 -->
  <div v-if="invalidId"></div>

  <!-- 跨租户 / 不存在：显式空态，不渲染空页 -->
  <el-alert
    v-else-if="notFound"
    type="error"
    :closable="false"
    show-icon
    title="项目不存在或不属于当前租户"
  >
    <template #default>
      <el-button size="small" type="primary" @click="goList">返回列表</el-button>
    </template>
  </el-alert>

  <!-- 正常视图 -->
  <div v-else v-loading="loading" class="gitee-detail">
    <template v-if="detail">
      <!-- ============================ 头部卡片 ============================ -->
      <el-card shadow="never" style="margin-bottom: 12px">
        <div class="hd">
          <div class="hd-title">
            <span class="proj-name">{{ project?.name || '未命名项目' }}</span>
            <el-tag
              v-if="project?.status"
              :type="(GITEE_PROJECT_STATUS_TAG[project.status] as any) || 'info'"
              effect="dark"
              size="small"
            >{{ GITEE_PROJECT_STATUS_LABEL[project.status] || project.status }}</el-tag>
            <span class="repo-name">{{ project?.repoName || '—' }}</span>
          </div>
          <div class="hd-ops">
            <el-button size="small" @click="goList">
              <el-icon><Back /></el-icon>返回列表
            </el-button>
            <el-button v-if="project?.htmlUrl" size="small" type="primary" @click="openGitee">
              <el-icon><Link /></el-icon>跳转 Gitee
            </el-button>
            <el-button size="small" :loading="refreshing" @click="refreshAll">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
          </div>
        </div>

        <!-- 创建失败 -->
        <el-alert
          v-if="project?.status === 'FAILED'"
          type="error"
          :closable="false"
          show-icon
          style="margin-top: 10px"
          :title="project.errorMsg || '建仓失败'"
        >
          <template #default>
            <el-button
              v-if="canManage"
              size="small"
              type="danger"
              :loading="retrying"
              @click="retryCreate"
            >重试建仓</el-button>
          </template>
        </el-alert>

        <!-- 创建中 -->
        <el-alert
          v-else-if="project?.status === 'CREATING'"
          type="info"
          :closable="false"
          show-icon
          style="margin-top: 10px"
          title="项目正在创建中"
          description="仓库与 Webhook 正在后台创建，完成后状态将变为「可用」。可点击右上角「刷新」查看进度。"
        />
      </el-card>

      <!-- ============================ 五个 Tab ============================ -->
      <el-card shadow="never">
        <el-tabs v-model="activeTab" @tab-change="onTabChange">
          <!-- ---------------- 概览 ---------------- -->
          <el-tab-pane label="概览" name="overview">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="项目名称">{{ project?.name || '—' }}</el-descriptions-item>
              <el-descriptions-item label="仓库名">{{ project?.repoName || '—' }}</el-descriptions-item>
              <el-descriptions-item label="归属部门">
                {{ project?.departmentId != null ? '部门 #' + project.departmentId : '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="可见性">
                {{ project?.visibility ? (GITEE_VISIBILITY_LABEL[project.visibility] || project.visibility) : '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="默认分支">{{ project?.defaultBranch || '—' }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag
                  v-if="project?.status"
                  :type="(GITEE_PROJECT_STATUS_TAG[project.status] as any) || 'info'"
                  size="small"
                >{{ GITEE_PROJECT_STATUS_LABEL[project.status] || project.status }}</el-tag>
                <template v-else>—</template>
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ fmtTime(project?.createdAt) }}</el-descriptions-item>
              <el-descriptions-item label="创建人">
                {{ project?.createdBy != null ? '用户 #' + project.createdBy : '—' }}
              </el-descriptions-item>
            </el-descriptions>

            <!-- 仓库卡片 -->
            <el-divider content-position="left">仓库</el-divider>
            <template v-if="repository?.cloneCommand || repository?.htmlUrl || repository?.sshUrl">
              <div class="kv">
                <span class="kv-label">克隆命令</span>
                <div class="clone-row">
                  <el-input :model-value="repository.cloneCommand" readonly size="small">
                    <template #append>
                      <el-button @click="copyText(repository.cloneCommand || '')">
                        <el-icon><CopyDocument /></el-icon>复制
                      </el-button>
                    </template>
                  </el-input>
                </div>
              </div>
              <div class="kv">
                <span class="kv-label">仓库地址</span>
                <div class="link-row">
                  <el-link v-if="repository.sshUrl" type="primary" :href="repository.sshUrl" target="_blank" rel="noopener">SSH {{ repository.sshUrl }}</el-link>
                  <el-link v-if="repository.httpsUrl" type="primary" :href="repository.httpsUrl" target="_blank" rel="noopener">HTTPS {{ repository.httpsUrl }}</el-link>
                  <el-link v-if="repository.htmlUrl" type="primary" :href="repository.htmlUrl" target="_blank" rel="noopener">Gitee 网页 {{ repository.htmlUrl }}</el-link>
                </div>
              </div>
            </template>
            <el-alert
              v-else
              type="info"
              :closable="false"
              title="仓库尚未就绪"
              description="建仓仍在后台进行，仓库信息就绪后会出现在这里。请稍后点击「刷新」。"
            />

            <!-- Webhook 卡片 -->
            <el-divider content-position="left">Webhook</el-divider>
            <div class="kv">
              <span class="kv-label">配置状态</span>
              <el-tag v-if="webhook?.configured" type="success">已配置</el-tag>
              <el-tag v-else type="warning">未配置</el-tag>
            </div>
            <div v-if="webhook?.configured" class="kv">
              <span class="kv-label">Hook ID</span><span>{{ webhook.hookId != null ? webhook.hookId : '—' }}</span>
            </div>
            <div v-if="webhook?.configured" class="kv">
              <span class="kv-label">订阅事件</span>
              <div class="evt-tags">
                <el-tag v-for="ev in webhookEvents" :key="ev" size="small" type="info">{{ ev }}</el-tag>
                <span v-if="!webhookEvents.length" class="muted">（无）</span>
              </div>
            </div>
            <div class="kv">
              <span class="kv-label">密钥</span>
              <el-tag v-if="webhook?.secretConfigured" type="success">密钥已设置</el-tag>
              <el-tag v-else type="warning">密钥未设置</el-tag>
            </div>
            <el-alert
              type="info"
              :closable="false"
              style="margin-top: 8px"
              title="提示"
              description="订阅 Push / 合并请求 / Issue / 评论 等事件后，Gitee 上的代码活动会经 Webhook 实时回流到本平台。"
            />

            <!-- 危险操作 -->
            <el-divider v-if="canManage" content-position="left">危险操作</el-divider>
            <div v-if="canManage" class="danger-ops">
              <el-button type="warning" size="small" :loading="deleting" @click="deleteKeepRepo">
                删除项目（保留 Gitee 仓库）
              </el-button>
              <el-button type="danger" size="small" :loading="deleting" @click="deleteWithRepo">
                删除项目并删除 Gitee 仓库
              </el-button>
            </div>
          </el-tab-pane>

          <!-- ---------------- 成员 ---------------- -->
          <el-tab-pane label="成员" name="members">
            <div class="pane-head">
              <span class="muted small">协作者与同步状态。来源为「Gitee 侧添加」表示在 Gitee 网页直接添加、由定时校准捞回。</span>
              <div>
                <el-button size="small" :loading="membersLoading" @click="loadMembers">刷新</el-button>
                <el-button v-if="canManage" size="small" type="primary" @click="openAddDlg">添加成员</el-button>
              </div>
            </div>
            <el-table v-loading="membersLoading" :data="members" stripe>
              <el-table-column label="用户" min-width="120">
                <template #default="{ row }">用户 #{{ row.userId }}</template>
              </el-table-column>
              <el-table-column label="Gitee 账号" min-width="160">
                <template #default="{ row }">
                  <span v-if="row.giteeUsername">{{ row.giteeUsername }}</span>
                  <el-tag v-else type="info">未绑定</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="角色" min-width="140">
                <template #default="{ row }">{{ GITEE_MEMBER_ROLE_LABEL[row.role] || row.role || '—' }}</template>
              </el-table-column>
              <el-table-column label="来源" min-width="120">
                <template #default="{ row }">{{ GITEE_MEMBER_SOURCE_LABEL[row.source] || row.source || '—' }}</template>
              </el-table-column>
              <el-table-column label="同步状态" min-width="120">
                <template #default="{ row }">
                  <el-tooltip v-if="row.syncStatus === 'FAILED' && row.lastError" :content="row.lastError" placement="top">
                    <el-tag :type="(GITEE_SYNC_STATUS_TAG[row.syncStatus] as any) || 'info'" size="small">
                      {{ GITEE_SYNC_STATUS_LABEL[row.syncStatus] || row.syncStatus }}
                    </el-tag>
                  </el-tooltip>
                  <el-tag v-else :type="(GITEE_SYNC_STATUS_TAG[row.syncStatus] as any) || 'info'" size="small">
                    {{ GITEE_SYNC_STATUS_LABEL[row.syncStatus] || row.syncStatus || '—' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="同步时间" width="160">
                <template #default="{ row }">{{ fmtTime(row.syncedAt) }}</template>
              </el-table-column>
              <el-table-column v-if="canManage" label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button text type="danger" size="small" @click="removeMember(row)">移除</el-button>
                </template>
              </el-table-column>
              <template #empty><el-empty description="暂无成员" :image-size="60" /></template>
            </el-table>
          </el-tab-pane>

          <!-- ---------------- 文件 ---------------- -->
          <el-tab-pane label="文件" name="files">
            <div class="pane-head">
              <div class="file-bar">
                <el-select v-model="currentRef" size="small" style="width: 220px" placeholder="选择分支" @change="onBranchChange">
                  <el-option v-for="b in branches" :key="b.name" :label="b.name" :value="b.name" />
                </el-select>
                <el-button size="small" :loading="contentsLoading" @click="loadContents">刷新目录</el-button>
                <el-button v-if="canManage" size="small" type="primary" @click="openUploadDlg">
                  <el-icon><Upload /></el-icon>上传文件
                </el-button>
              </div>
            </div>

            <el-alert
              v-if="branchesDegraded"
              type="warning"
              :closable="false"
              show-icon
              style="margin-bottom: 8px"
              title="分支列表不完整"
              :description="(degradedReason || 'Gitee 暂不可达') + '。已默认使用默认分支，列表可能不全，但可正常浏览默认分支内容。'"
            />

            <!-- 路径面包屑 -->
            <div class="breadcrumb">
              <el-button size="small" text :disabled="!currentPath" @click="gotoParent">
                <el-icon><Back /></el-icon>上级
              </el-button>
              <span class="crumb-root" @click="gotoSegment('')">根目录</span>
              <template v-for="(seg, i) in pathSegments" :key="seg.path">
                <span class="crumb-sep">/</span>
                <span
                  class="crumb-seg"
                  :class="{ last: i === pathSegments.length - 1 }"
                  @click="gotoSegment(seg.path)"
                >{{ seg.name }}</span>
              </template>
              <span v-if="!currentPath" class="muted small">（根）</span>
            </div>

            <!-- 目录 -->
            <template v-if="contents && contents.kind === 'dir'">
              <el-table v-loading="contentsLoading" :data="contents.items || []" stripe>
                <el-table-column label="名称" min-width="240">
                  <template #default="{ row }">
                    <span class="entry" @click="openEntry(row)">
                      <el-icon v-if="row.type === 'dir'"><FolderOpened /></el-icon>
                      <el-icon v-else><Document /></el-icon>
                      {{ row.name }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="类型" width="90">
                  <template #default="{ row }">{{ row.type === 'dir' ? '目录' : '文件' }}</template>
                </el-table-column>
                <el-table-column label="大小" width="120">
                  <template #default="{ row }">{{ row.type === 'dir' ? '—' : fmtSize(row.size) }}</template>
                </el-table-column>
                <el-table-column label="SHA" min-width="120" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.sha || '—' }}</template>
                </el-table-column>
                <template #empty>
                  <div>
                    <el-empty
                      :image-size="60"
                      :description="contents.empty ? contents.note || '该目录暂无内容' : '目录为空'"
                    />
                    <!-- 新建仓库必然是空的（Gitee 对空仓库的 contents 返回 404，后端已降级为空目录）。
                         这是正常态，所以这里给一句「下一步做什么」，而不是让人以为出错。 -->
                    <div v-if="contents.empty" class="muted small" style="text-align: center">
                      仓库刚建好还没有提交：本地 <code>git push</code>，或用上方「上传文件」提交第一个文件。
                    </div>
                  </div>
                </template>
              </el-table>
            </template>

            <!-- 文件 -->
            <template v-else-if="contents && contents.kind === 'file'">
              <div class="file-meta">
                <span>文件：{{ contents.name }}</span>
                <span>大小：{{ fmtSize(contents.size) }}</span>
                <span>SHA：{{ contents.sha || '—' }}</span>
                <el-link v-if="contents.downloadUrl" type="primary" :href="contents.downloadUrl" target="_blank" rel="noopener">下载</el-link>
              </div>
              <el-alert
                v-if="contents.binary || contents.contentOmitted"
                type="info"
                :closable="false"
                style="margin-bottom: 8px"
                title="无法预览"
                description="该文件为二进制或体积过大，不在此预览。可通过上方「下载」获取完整内容。"
              />
              <pre v-else class="file-pre">{{ contents.text || '（空文件）' }}</pre>
            </template>

            <el-empty v-else-if="!contentsLoading" description="暂无内容" :image-size="60" />
          </el-tab-pane>

          <!-- ---------------- 提交记录 ---------------- -->
          <el-tab-pane label="提交记录" name="commits">
            <div class="pane-head">
              <span class="muted small">网页上传与本地 git push（经 Webhook 回流）的提交在此合流。</span>
            </div>
            <el-table v-loading="commitLoading" :data="commits" stripe>
              <el-table-column label="提交" width="130">
                <template #default="{ row }">
                  <el-tooltip :content="row.sha || ''" placement="top">
                    <span class="mono">{{ row.shortSha || '—' }}</span>
                  </el-tooltip>
                </template>
              </el-table-column>
              <el-table-column label="分支" width="140">
                <template #default="{ row }">{{ row.branch || '—' }}</template>
              </el-table-column>
              <el-table-column label="提交信息" min-width="240" show-overflow-tooltip>
                <template #default="{ row }">{{ row.message || '—' }}</template>
              </el-table-column>
              <el-table-column label="作者" width="140">
                <template #default="{ row }">
                  <span>{{ row.authorName || '—' }}</span>
                  <el-tag v-if="row.authorUserId != null" size="small" type="success">已映射 #{{ row.authorUserId }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="110">
                <template #default="{ row }">
                  <el-tag v-if="row.source" size="small">{{ GITEE_COMMIT_SOURCE_LABEL[row.source] || row.source }}</el-tag>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column label="时间" width="170">
                <template #default="{ row }">{{ fmtTime(row.committedAt) }}</template>
              </el-table-column>
              <template #empty><el-empty description="暂无提交" :image-size="60" /></template>
            </el-table>
            <el-pagination
              v-model:current-page="commitPage"
              :page-size="commitSize"
              :total="commitTotal"
              layout="prev, pager, next, total"
              size="small"
              style="margin-top: 8px"
              @current-change="loadCommits"
            />
          </el-tab-pane>

          <!-- ---------------- 事件流 ---------------- -->
          <el-tab-pane label="事件流" name="events">
            <div class="pane-head">
              <div class="file-bar">
                <el-select v-model="eventType" size="small" style="width: 180px" placeholder="事件类型" @change="onEventTypeChange">
                  <el-option v-for="t in GITEE_EVENT_TYPES" :key="t.value" :label="t.label" :value="t.value" />
                </el-select>
                <span class="muted small">Gitee 网页上的操作经 Webhook 回流；重复投递会按幂等键去重，不会重复出现。</span>
              </div>
            </div>
            <el-table v-loading="eventLoading" :data="events" stripe>
              <el-table-column label="类型" width="120">
                <template #default="{ row }">
                  <el-tag :type="(GITEE_EVENT_TYPE_TAG[row.eventType] as any) || 'info'" size="small">
                    {{ GITEE_EVENT_TYPE_LABEL[row.eventType] || row.eventType || '—' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="Gitee 事件" width="150" prop="giteeEvent" show-overflow-tooltip />
              <el-table-column label="动作" width="100" prop="action" />
              <el-table-column label="标题" min-width="200" prop="title" show-overflow-tooltip />
              <el-table-column label="摘要" min-width="200" prop="summary" show-overflow-tooltip />
              <el-table-column label="引用" width="130" prop="refName" show-overflow-tooltip />
              <el-table-column label="提交" width="120">
                <template #default="{ row }"><span class="mono">{{ row.shortSha || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="操作人" min-width="200">
                <template #default="{ row }">
                  <span>{{ row.actorLogin || '—' }}</span>
                  <el-tag v-if="row.actorMapped" type="success" size="small">已映射平台用户 #{{ row.actorUserId }}</el-tag>
                  <el-tag v-else type="info" size="small">未映射</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="发生时间" width="160">
                <template #default="{ row }">{{ fmtTime(row.occurredAt) }}</template>
              </el-table-column>
              <el-table-column label="接收时间" width="160">
                <template #default="{ row }">{{ fmtTime(row.receivedAt) }}</template>
              </el-table-column>
              <template #empty><el-empty description="暂无事件" :image-size="60" /></template>
            </el-table>
            <el-pagination
              v-model:current-page="eventPage"
              :page-size="eventSize"
              :total="eventTotal"
              layout="prev, pager, next, total"
              size="small"
              style="margin-top: 8px"
              @current-change="loadEvents"
            />
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>
  </div>

  <!-- ============================ 添加成员对话框 ============================ -->
  <el-dialog v-model="addDlg" title="添加成员" width="680px">
    <el-alert
      type="info"
      :closable="false"
      style="margin-bottom: 8px"
      title="提示"
      description="未绑定 Gitee 的成员添加后将处于「待同步（PENDING）」，待其绑定 Gitee 后由后台同步；后端不会替其编造 Gitee 账号。"
    />
    <div class="file-bar" style="margin-bottom: 8px">
      <el-input v-model="candidateKeyword" size="small" placeholder="按姓名 / 工号搜索" clearable style="width: 240px" @keyup.enter="searchCandidates" />
      <el-button size="small" :loading="candLoading" @click="searchCandidates">搜索</el-button>
    </div>
    <el-table v-loading="candLoading" :data="candidates" stripe height="300">
      <el-table-column label="选择" width="60">
        <template #default="{ row }">
          <el-radio v-model="selectedUserId" :value="row.userId" :disabled="row.alreadyMember" />
        </template>
      </el-table-column>
      <el-table-column label="姓名" width="120" prop="name" />
      <el-table-column label="部门" width="110">
        <template #default="{ row }">{{ row.departmentId != null ? '部门 #' + row.departmentId : '—' }}</template>
      </el-table-column>
      <el-table-column label="工号" width="130" prop="employeeNo" />
      <el-table-column label="Gitee 账号" min-width="160">
        <template #default="{ row }">
          <span v-if="row.giteeUsername">{{ row.giteeUsername }}</span>
          <el-tag v-else type="warning">未绑定</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.alreadyMember" size="small" type="info">已在项目</el-tag>
          <span v-else class="muted small">可添加</span>
        </template>
      </el-table-column>
      <template #empty><el-empty description="无候选成员" :image-size="50" /></template>
    </el-table>
    <el-form label-width="80px" size="small" style="margin-top: 12px">
      <el-form-item label="角色">
        <el-select v-model="memberRole" style="width: 100%">
          <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button size="small" @click="addDlg = false">取消</el-button>
      <el-button size="small" type="primary" :loading="adding" @click="confirmAdd">确认添加</el-button>
    </template>
  </el-dialog>

  <!-- ============================ 上传文件对话框 ============================ -->
  <el-dialog v-model="uploadDlg" title="上传文件（提交文本内容）" width="640px">
    <el-alert
      type="info"
      :closable="false"
      style="margin-bottom: 8px"
      title="仅提交文本内容"
      description="此路径提交的是文本正文；二进制文件请使用 git 推送到 Gitee。"
    />
    <el-form label-width="90px" size="small">
      <el-form-item label="文件路径" required>
        <el-input v-model="uploadForm.path" placeholder="如 src/main/java/App.java" />
      </el-form-item>
      <el-form-item label="提交信息">
        <el-input v-model="uploadForm.message" placeholder="可选，默认由系统生成" />
      </el-form-item>
      <el-form-item label="分支">
        <el-input v-model="uploadForm.branch" placeholder="默认当前分支" />
      </el-form-item>
      <el-form-item label="文件内容" required>
        <el-input v-model="uploadForm.content" type="textarea" :rows="8" placeholder="输入或选择本地文本文件" />
      </el-form-item>
      <el-form-item label="本地文件">
        <input
          type="file"
          accept=".txt,.md,.json,.csv,.yml,.yaml,.xml,.html,.js,.ts,.vue,.java,.py,.sql,.sh,.properties"
          @change="onPickFile"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button size="small" @click="uploadDlg = false">取消</el-button>
      <el-button size="small" type="primary" :loading="uploading" @click="confirmUpload">提交</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  giteeProjectDetail, giteeRetryProject, giteeDeleteProject,
  giteeMembers, giteeMemberCandidates, giteeAddMember, giteeRemoveMember,
  giteeBranches, giteeContents, giteeUpload, giteeCommits, giteeEvents,
  giteeConfig, giteeErrMsg,
  type GiteeProjectDetail, type GiteeProject, type GiteeRepository, type GiteeWebhook,
  type GiteeMember, type GiteeMemberCandidate, type GiteeBranch,
  type GiteeContentsResult, type GiteeContentEntry, type GiteeCommitItem,
  type GiteeEventItem, type GiteeConfig
} from '@/api/gitee'

import {
  GITEE_PROJECT_STATUS_LABEL, GITEE_PROJECT_STATUS_TAG, GITEE_VISIBILITY_LABEL,
  GITEE_MEMBER_ROLE_LABEL, GITEE_MEMBER_ROLES, GITEE_MEMBER_SOURCE_LABEL,
  GITEE_SYNC_STATUS_LABEL, GITEE_SYNC_STATUS_TAG, GITEE_COMMIT_SOURCE_LABEL,
  GITEE_EVENT_TYPES, GITEE_EVENT_TYPE_LABEL, GITEE_EVENT_TYPE_TAG
} from '@/constants/permissions'

// ----------------------------- 路由参数校验 -----------------------------
const route = useRoute()
const router = useRouter()

const projectId = Number(route.params.id)
const invalidId = !Number.isFinite(projectId) || projectId <= 0

if (invalidId) {
  ElMessage.error('项目 ID 无效')
  router.replace('/gitee/projects')
}

// ----------------------------- 顶层状态 -----------------------------
const loading = ref(false)
const refreshing = ref(false)
const notFound = ref(false)
const detail = ref<GiteeProjectDetail | null>(null)
const project = computed<GiteeProject | undefined>(() => detail.value?.project)
const repository = computed<GiteeRepository | undefined>(() => detail.value?.repository)
const webhook = computed<GiteeWebhook | undefined>(() => detail.value?.webhook)
const canManage = computed<boolean>(() => detail.value?.canManage ?? false)

// Webhook 事件归一化（可能是 string[] 也可能是逗号拼接的 string）
const webhookEvents = computed<string[]>(() => {
  const ev = webhook.value?.events
  if (!ev) return []
  return Array.isArray(ev) ? ev : String(ev || '').split(',').filter(Boolean)
})

// 角色下拉：优先 config 的 roleOptions，降级用 GITEE_MEMBER_ROLES
const roleOptions = ref<{ value: string; label: string }[]>([...GITEE_MEMBER_ROLES])

// ----------------------------- 详情加载 -----------------------------
async function loadDetail() {
  if (invalidId) return
  loading.value = true
  try {
    const d = await giteeProjectDetail(projectId)
    detail.value = d
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 404) {
      notFound.value = true
      return
    }
    ElMessage.error(giteeErrMsg(e, '项目详情加载失败'))
  } finally {
    loading.value = false
  }
}

async function loadConfig() {
  try {
    const c: GiteeConfig = await giteeConfig()
    if (c?.roleOptions?.length) roleOptions.value = c.roleOptions
  } catch {
    /* config 不可用时降级到 GITEE_MEMBER_ROLES */
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await loadDetail()
    // 重置各页已加载标记，强制回到当前数据
    loadedTabs.members = false
    loadedTabs.files = false
    loadedTabs.commits = false
    loadedTabs.events = false
    const t = activeTab.value
    if (t !== 'overview') await loadTab(t)
  } finally {
    refreshing.value = false
  }
}

function goList() {
  router.push('/gitee/projects')
}
function openGitee() {
  if (project.value?.htmlUrl) window.open(project.value.htmlUrl, '_blank', 'noopener')
}

const retrying = ref(false)
async function retryCreate() {
  retrying.value = true
  try {
    await giteeRetryProject(projectId)
    ElMessage.success('已重新触发建仓')
    await loadDetail()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '重试失败'))
  } finally {
    retrying.value = false
  }
}

const deleting = ref(false)
async function deleteKeepRepo() {
  try {
    await ElMessageBox.confirm(
      '确认删除该项目？Gitee 仓库将保留，可稍后重新关联。',
      '删除项目（保留仓库）',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  deleting.value = true
  try {
    const r = await giteeDeleteProject(projectId, false)
    ElMessage.success(r.note || '已删除项目（保留仓库）')
    router.push('/gitee/projects')
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '删除失败'))
  } finally {
    deleting.value = false
  }
}
async function deleteWithRepo() {
  try {
    await ElMessageBox.confirm(
      '此操作将同时删除 Gitee 仓库，且不可恢复。确认继续？',
      '删除项目并删除 Gitee 仓库',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  deleting.value = true
  try {
    const r = await giteeDeleteProject(projectId, true)
    ElMessage.success(r.note || '已删除项目及 Gitee 仓库')
    router.push('/gitee/projects')
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '删除失败'))
  } finally {
    deleting.value = false
  }
}

// ----------------------------- Tab 懒加载 -----------------------------
const activeTab = ref('overview')
const loadedTabs = reactive<Record<string, boolean>>({})

function onTabChange(name: string | number) {
  const key = String(name)
  if (!loadedTabs[key]) void loadTab(key)
}

async function loadTab(name: string) {
  if (name === 'members') await loadMembers()
  else if (name === 'files') { await loadBranches(); await loadContents() }
  else if (name === 'commits') await loadCommits()
  else if (name === 'events') await loadEvents()
}

// ----------------------------- 成员 -----------------------------
const members = ref<GiteeMember[]>([])
const membersLoading = ref(false)

async function loadMembers() {
  membersLoading.value = true
  loadedTabs.members = true
  try {
    const r = await giteeMembers(projectId)
    members.value = r.items || []
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '成员加载失败'))
  } finally {
    membersLoading.value = false
  }
}

const addDlg = ref(false)
const candLoading = ref(false)
const adding = ref(false)
const candidateKeyword = ref('')
const candidates = ref<GiteeMemberCandidate[]>([])
const selectedUserId = ref<number | null>(null)
const memberRole = ref('READ')

async function openAddDlg() {
  addDlg.value = true
  candidateKeyword.value = ''
  selectedUserId.value = null
  memberRole.value = roleOptions.value[0]?.value || 'READ'
  await searchCandidates()
}

async function searchCandidates() {
  candLoading.value = true
  try {
    const r = await giteeMemberCandidates(projectId, candidateKeyword.value || undefined)
    candidates.value = r.items || []
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '候选成员加载失败'))
  } finally {
    candLoading.value = false
  }
}

async function confirmAdd() {
  const cand = candidates.value.find((c) => c.userId === selectedUserId.value)
  if (!cand) { ElMessage.warning('请先选择一名候选成员'); return }
  if (cand.alreadyMember) { ElMessage.warning('该成员已在项目中'); return }
  adding.value = true
  try {
    const r = await giteeAddMember(projectId, {
      userId: cand.userId,
      role: memberRole.value,
      giteeUsername: cand.giteeUsername
    })
    ElMessage.success(r.note || '已添加成员')
    addDlg.value = false
    await loadMembers()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '添加成员失败'))
  } finally {
    adding.value = false
  }
}

async function removeMember(row: GiteeMember) {
  try {
    await ElMessageBox.confirm(
      `确认将成员「${row.giteeUsername || ('用户 #' + row.userId)}」移出该项目？`,
      '移除成员',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const r = await giteeRemoveMember(projectId, row.id)
    ElMessage.success(r.note || '已移除成员')
    await loadMembers()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '移除失败'))
  }
}

// ----------------------------- 文件 -----------------------------
const branches = ref<GiteeBranch[]>([])
const branchesDegraded = ref(false)
const degradedReason = ref('')
const currentRef = ref('')
const currentPath = ref('')
const contents = ref<GiteeContentsResult | null>(null)
const contentsLoading = ref(false)

const pathSegments = computed<{ name: string; path: string }[]>(() => {
  if (!currentPath.value) return []
  const parts = currentPath.value.split('/').filter(Boolean)
  const out: { name: string; path: string }[] = []
  let acc = ''
  for (const p of parts) {
    acc = acc ? acc + '/' + p : p
    out.push({ name: p, path: acc })
  }
  return out
})

async function loadBranches() {
  try {
    const r = await giteeBranches(projectId)
    branches.value = r.items || []
    branchesDegraded.value = !!r.degraded
    degradedReason.value = r.degradedReason || ''
    if (!currentRef.value) currentRef.value = r.defaultBranch || (r.items?.[0]?.name || '')
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '分支列表加载失败'))
  }
}

async function loadContents() {
  contentsLoading.value = true
  try {
    const r = await giteeContents(projectId, {
      path: currentPath.value || undefined,
      ref: currentRef.value || undefined
    })
    contents.value = r
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '目录内容加载失败'))
  } finally {
    contentsLoading.value = false
  }
}

function onBranchChange() {
  currentPath.value = ''
  loadedTabs.commits = false
  void loadContents()
  if (loadedTabs.commits) void loadCommits()
}

function openEntry(entry: GiteeContentEntry) {
  currentPath.value = entry.path || ''
  void loadContents()
}
function gotoSegment(path: string) {
  currentPath.value = path
  void loadContents()
}
function gotoParent() {
  if (!currentPath.value) return
  const idx = currentPath.value.lastIndexOf('/')
  currentPath.value = idx >= 0 ? currentPath.value.slice(0, idx) : ''
  void loadContents()
}

function fmtSize(n?: number): string {
  if (n == null) return '—'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

// 上传
const uploadDlg = ref(false)
const uploading = ref(false)
const uploadForm = ref({ path: '', message: '', branch: '', content: '' })

function openUploadDlg() {
  uploadForm.value = {
    path: currentPath.value ? currentPath.value + '/' : '',
    message: '',
    branch: currentRef.value || '',
    content: ''
  }
  uploadDlg.value = true
}

function onPickFile(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  const reader = new FileReader()
  reader.onload = () => { uploadForm.value.content = String(reader.result ?? '') }
  reader.onerror = () => { ElMessage.warning('文件读取失败') }
  try {
    reader.readAsText(f)
  } catch {
    ElMessage.warning('文件读取失败')
  }
}

async function confirmUpload() {
  if (!uploadForm.value.path) { ElMessage.warning('请填写文件路径'); return }
  if (!uploadForm.value.content) { ElMessage.warning('请填写文件内容或选择本地文本文件'); return }
  uploading.value = true
  try {
    const r = await giteeUpload(projectId, {
      path: uploadForm.value.path,
      content: uploadForm.value.content,
      message: uploadForm.value.message || undefined,
      branch: uploadForm.value.branch || undefined
    })
    ElMessage.success('上传成功，提交 ' + (r.shortSha || ''))
    uploadDlg.value = false
    await loadContents()
    loadedTabs.commits = false
    await loadCommits()
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '上传失败'))
  } finally {
    uploading.value = false
  }
}

// ----------------------------- 提交记录 -----------------------------
const commits = ref<GiteeCommitItem[]>([])
const commitPage = ref(1)
const commitSize = ref(20)
const commitTotal = ref(0)
const commitLoading = ref(false)

async function loadCommits() {
  commitLoading.value = true
  loadedTabs.commits = true
  try {
    const r = await giteeCommits(projectId, {
      branch: currentRef.value || undefined,
      page: commitPage.value,
      size: commitSize.value
    })
    commits.value = r.items || []
    commitTotal.value = r.total ?? 0
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '提交记录加载失败'))
  } finally {
    commitLoading.value = false
  }
}

// ----------------------------- 事件流 -----------------------------
const events = ref<GiteeEventItem[]>([])
const eventType = ref('')
const eventPage = ref(1)
const eventSize = ref(20)
const eventTotal = ref(0)
const eventLoading = ref(false)

function onEventTypeChange() {
  eventPage.value = 1
  void loadEvents()
}

async function loadEvents() {
  eventLoading.value = true
  loadedTabs.events = true
  try {
    const r = await giteeEvents(projectId, {
      eventType: eventType.value || undefined,
      page: eventPage.value,
      size: eventSize.value
    })
    events.value = r.items || []
    eventTotal.value = r.total ?? 0
  } catch (e: unknown) {
    ElMessage.error(giteeErrMsg(e, '事件流加载失败'))
  } finally {
    eventLoading.value = false
  }
}

// ----------------------------- 复制（含降级） -----------------------------
async function copyText(text: string) {
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      ElMessage.success('已复制')
      return
    }
  } catch {
    /* 走降级 */
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动复制')
  }
}

// ----------------------------- 工具 -----------------------------
function fmtTime(t?: string): string {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 16)
}

// ----------------------------- 初始化 -----------------------------
onMounted(() => {
  void loadDetail()
  void loadConfig()
})

// 监听分支变化（由文件页外触发时）也刷新提交
watch(currentRef, () => { loadedTabs.commits = false })
</script>

<style scoped>
.gitee-detail { padding: 4px; }
.hd { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.hd-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.proj-name { font-size: 18px; font-weight: 700; }
.repo-name { color: var(--el-text-color-secondary); font-size: 13px; }
.hd-ops { display: flex; gap: 6px; }
.kv { display: flex; align-items: flex-start; gap: 10px; margin: 6px 0; font-size: 13px; }
.kv-label { width: 72px; color: var(--el-text-color-secondary); flex-shrink: 0; }
.clone-row { flex: 1; max-width: 560px; }
.link-row { display: flex; flex-direction: column; gap: 2px; }
.evt-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.danger-ops { display: flex; gap: 10px; flex-wrap: wrap; }
.pane-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.file-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.breadcrumb { display: flex; align-items: center; gap: 4px; margin: 8px 0; font-size: 13px; flex-wrap: wrap; }
.crumb-root, .crumb-seg { cursor: pointer; color: var(--el-color-primary); }
.crumb-seg.last { color: var(--el-text-color-primary); font-weight: 600; cursor: default; }
.crumb-sep { color: var(--el-text-color-secondary); }
.entry { cursor: pointer; color: var(--el-color-primary); display: inline-flex; align-items: center; gap: 4px; }
.file-meta { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.file-pre {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 420px;
  overflow: auto;
}
.mono { font-family: monospace; }
.muted { color: #909399; }
.small { font-size: 12px; }
</style>
