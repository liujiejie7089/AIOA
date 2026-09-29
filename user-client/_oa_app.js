/* ============================================================================
   OA 形态应用层（新版 · 协同工作台）
   ----------------------------------------------------------------------------
   设计约束
   ① 只读既有全域 state 与 API：不新开请求口径，不复制业务分支。
      待办 = state.todoApprovals（已由 loadTodoApprovals() 合并双引擎）；
      我发起的 = state.approvals；抄送 = state.ccApprovals；本部门 = state.deptOrders。
   ② 审批决策不自己实现：走既有 askApprovalNote() → commitApprovalDecision()
      （那一个函数里是「多级 / 单级」分流的唯一判定点）。
   ③ 与经典形态零耦合：经典 page-* 一行未改，靠 body.auth 变化 + localStorage 记忆联动。
   ============================================================================ */
(function(){
'use strict';

/* ------------------------------------------------------------------ 0. 状态 */
var S = {
  mode:'classic',        // 'oa' | 'classic'
  view:'home',           // 当前 OA 视图
  from:'home',           // 子页来源（返回用）
  rail:'tasks',          // 任务页左导轨
  apprScope:'todo',      // 审批面板分段
  convId:null,           // 对话坞会话（与经典 state.conversationId 分账）
  worker:null,           // 数字员工
  expert:null,           // 专家
  busy:false,
  controller:null,
  apprDetail:null,       // 正在看的审批单 {id, scope}
  deptId:null,           // 部门筛选（null = 全部）
  orgQ:'', kbQ:'',
  org:null,              // 组织数据缓存（profile / departments / members）
  leave:null             // 我的请假（日程数据源之一）
};
var LS_MODE = 'aioa_mode';
/* 默认形态：全新访客（以及登出之后）进入新版。
   只有用户显式点过「切换布局」并留下记忆时，才尊重那份记忆 ——
   否则「默认展示新版」会被一条陈旧的 localStorage 值悄悄推翻。 */
var MODE_DEFAULT = 'oa';
var ROBOT = null;        // 数字人锚点元素

function $o(id){ return document.getElementById(id); }
function has(v){ return v !== null && v !== undefined && v !== ''; }
function arr(v){ return asArray(v); }
function txt(s){ return esc(String(s == null ? '' : s)); }
function n(v){ return Number(v || 0); }
function ic(k, size){ return '<svg class="ic" style="width:'+(size||16)+'px;height:'+(size||16)+'px"><use href="#i-'+k+'"/></svg>'; }
function empty(t){ return '<div class="empty">'+ic('inbox',26)+'<div>'+txt(t)+'</div></div>'; }
function chip(cls, t){ return '<span class="chip '+cls+'">'+txt(t)+'</span>'; }
function dt(s){ return has(s) ? String(s).replace('T',' ').slice(0,16) : '—'; }
function day(s){ return has(s) ? String(s).slice(0,10) : '—'; }

var BIZ = {LEAVE:'请假', EXPENSE:'费用', PURCHASE:'采购', DOC:'文稿', RESULT:'成果',
           QUOTA:'额度扩容', TENANT_DELETE:'租户注销', ORG_DELETE:'组织注销', RESOURCE:'资源'};
function bizName(b){ return BIZ[b] || b || '其他'; }

/* 审批单状态 → 徽标（与经典 openTodoDetail 同口径） */
function statusChip(a){
  if(a.status === 'PENDING') return chip('wait','待审批');
  if(a.status === 'APPROVED') return chip('due','已通过');
  return chip('rej','已驳回');
}

/* ------------------------------------------------------------- 1. 双形态切换 */
function phoneEl(){ return document.querySelector('.phone'); }
function authed(){ return document.body.classList.contains('auth'); }

function applyMode(){
  var p = phoneEl(); if(!p) return;
  var on = (S.mode === 'oa') && authed();
  p.classList.toggle('oa-mode', on);
  state.mode = S.mode;                       // 便于自检脚本读取
  syncLayoutBtns();
  if(on) oaRender();
}

function setMode(m){
  S.mode = (m === 'oa') ? 'oa' : 'classic';
  try{ localStorage.setItem(LS_MODE, S.mode); }catch(e){}
  applyMode();
  toast(S.mode === 'oa' ? '已切换到「新版 · 协同工作台」' : '已切换到「原版 · 经典工作台」');
}

/* 切换布局：离开新版形态的唯一出口。两个形态的「我的」里各有一个按钮，都指向这里。 */
function toggleMode(){ setMode(S.mode === 'oa' ? 'classic' : 'oa'); }

/* 登出：回到默认形态并清掉本机记忆 —— 下一个使用者应看到默认（新版），
   而不是上一个人留在这台机器上的选择。 */
function resetMode(){
  S.mode = MODE_DEFAULT;
  try{ localStorage.removeItem(LS_MODE); }catch(e){}
}

/* 两个按钮都只是 S.mode 的镜像：不各自持有状态，也不写死「当前是哪个版本」之外的判断。
   title 说明点下去会去哪里 —— 否则在经典形态里看到「切换布局」会误以为会切到经典。 */
function syncLayoutBtns(){
  var to = (S.mode === 'oa') ? '经典工作台' : '协同工作台';
  document.querySelectorAll('.js-layout-switch').forEach(function(b){
    b.title = '切换到' + to;
    b.setAttribute('aria-label', '切换到' + to);
  });
}

/* ---------------------------------------------------------------- 2. OA 导航 */
var META = {
  home:    {t:'工作助手',      tab:'home'},
  collab:  {t:'AIOA 办公协同', tab:'collab'},
  kb:      {t:'知识库',        tab:'kb'},
  org:     {t:'部门',          tab:'org'},
  me:      {t:'我的',          tab:'me'},
  workers: {t:'数字员工',      tab:null, sub:1},
  experts: {t:'专家',          tab:null, sub:1},
  timers:  {t:'定时任务',      tab:null, sub:1},
  skills:  {t:'插件 · 技能',   tab:null, sub:1},
  recent:  {t:'最近会话',      tab:null, sub:1},
  appr:    {t:'审批详情',      tab:null, sub:1},
  /* 原先这四项会切回经典形态，现改为 OA 内视图：新版里不再有「悄悄跳到老版」的入口 */
  bill:    {t:'额度与账单',    tab:null, sub:1},
  log:     {t:'我的操作记录',  tab:null, sub:1},
  perm:    {t:'权限申请',      tab:null, sub:1},
  feedback:{t:'投诉与建议',    tab:null, sub:1}
};

function oaGo(view){
  if(!META[view]) return;
  // 子页记录来源，非子页复位来源为自身
  if(META[view].sub){ if(!META[S.view].sub) S.from = S.view; }
  else { S.from = view; }
  S.view = view;
  oaCloseDrawer(); oaCloseSheet();
  oaRender();
  var p = $o('v-' + view); if(p){ p.scrollTop = 0; var m = p.querySelector('.rail-main'); if(m) m.scrollTop = 0; }
  oaRefreshView(view);
}

/* 进入需要实时数据的子页时补一次拉取，再按同源 state 重绘。
   只在 oaGo 里触发（oaRender 不触发），因此不会自激。
   拉取动作一律复用经典形态已有的加载器，避免出现第二套口径。 */
function oaRefreshView(view){
  var p = null;
  if(view === 'bill')      p = API.ledger().then(function(r){ state.bill = arr(r); });
  else if(view === 'log')  p = API.logs().then(function(r){ state.log = arr(r); });
  else if(view === 'perm') p = (typeof refreshPermissions === 'function') ? refreshPermissions() : null;
  else if(view === 'feedback') p = (typeof reloadFeedback === 'function') ? reloadFeedback() : null;
  if(!p) return;
  p.catch(function(){}).then(function(){ if(S.mode === 'oa' && S.view === view) oaRender(); });
}

function oaRender(){
  var meta = META[S.view] || META.home;

  // 视图显隐
  document.querySelectorAll('#oaRoot .view').forEach(function(v){
    v.classList.toggle('on', v.id === 'v-' + S.view);
  });
  // 顶栏
  var t = $o('oaTitle'); if(t) t.textContent = meta.t;
  var left = $o('oaLeft');
  if(left){
    var isHomeTab = (S.view === 'home');
    left.innerHTML = ic(isHomeTab ? 'menu' : 'back', 20);
    left.setAttribute('aria-label', isHomeTab ? '打开目录' : '返回');
    left.onclick = function(){ if(isHomeTab) oaOpenDrawer(); else oaGo(S.from || 'home'); };
  }
  var right = $o('oaRight');
  if(right){
    var unread = (state.notifs && state.notifs.unread) || 0;
    right.innerHTML = (S.view === 'home' && unread > 0)
      ? '<span class="ab-pill" id="oaBell">'+ic('bell',15)+' '+n(unread)+'</span>' : '';
    var bell = $o('oaBell');
    if(bell) bell.onclick = function(){ oaGo('log'); };
  }
  // 底部 Tab
  document.querySelectorAll('#oaTabs .tab').forEach(function(x){
    x.classList.toggle('on', x.dataset.view === meta.tab);
  });
  // 任务数角标（与 rail 计数同源）
  var todo = arr(state.todoApprovals).length;
  var cnt = $o('oaTabCnt');
  if(cnt){
    if(todo > 0){ cnt.textContent = todo > 99 ? '99+' : todo; cnt.style.display = ''; }
    else cnt.style.display = 'none';
  }
  // 各页按需渲染
  if(S.view === 'home')    renderHome();
  if(S.view === 'collab')  renderCollab();
  if(S.view === 'kb')      renderKb();
  if(S.view === 'org')     renderOrg();
  if(S.view === 'me')      renderMe();
  if(S.view === 'workers') renderWorkers();
  if(S.view === 'experts') renderExperts();
  if(S.view === 'timers')  renderTimers();
  if(S.view === 'skills')  renderSkills();
  if(S.view === 'recent')  renderRecent();
  if(S.view === 'appr')    renderApprDetail();
  if(S.view === 'bill')    renderOaBill();
  if(S.view === 'log')     renderOaLog();
  if(S.view === 'perm')    renderOaPerm();
  if(S.view === 'feedback') renderOaFeedback();

  /* 回到首页时补一次三角落位。气泡可能是在别的视图里追加的（首页当时 display:none，
     量到零矩形、oaLayoutTails 直接返回）—— 那批三角就会停在初始态、不再指向数字人。
     这里先量一次；入场动画重放造成的中间帧偏差由 dockList 的 animationend 兜底。 */
  if(S.view === 'home'){
    oaLayoutTails();
    requestAnimationFrame(oaLayoutTails);
  }
}

/* 说明：本文件曾有一个 oaGoClassic(pageId)——切回经典形态并打开某个经典页。
   它被「我的」里 4 个账户入口与两处通知入口当作内部跳转用，结果是「在新版里点一下就被弹到老版」。
   现全部改为 OA 内视图（bill / log / perm / feedback），离开新版形态的唯一出口只剩
   「切换布局」按钮 → toggleMode()。故此函数已删除，不留半条逃生路。 */

/* --------------------------------------------------------------- 3. 首页渲染 */
function renderHome(){
  var ms = state.myStats || {};
  var k1 = $o('oaK1'), k2 = $o('oaK2'), k3 = $o('oaK3'), k4 = $o('oaK4');
  if(k1) k1.innerHTML = n(arr(state.todoApprovals).length) + '<span>项</span>';
  if(k2) k2.innerHTML = n(has(ms.myApplications) ? ms.myApplications : arr(state.approvals).length) + '<span>项</span>';
  if(k3) k3.innerHTML = n(state.ccUnread) + '<span>条</span>';
  if(k4) k4.innerHTML = n(has(ms.conversations) ? ms.conversations : 0) + '<span>个</span>';

  // 「合同待查看」这类提示条：有未读通知才出现，无数据则隐藏（不写死文案）
  var tag = $o('oaTag'); if(!tag) return;
  var items = arr(state.notifs && state.notifs.items);
  if(items.length && !$o('v-home').classList.contains('chatting')){
    var first = items[0] || {};
    tag.innerHTML = ic('doc',14) + ' ' + txt(first.title || first.content || '有新通知') ;
    tag.style.display = '';
    tag.onclick = function(){ oaGo('log'); };
  }else{
    tag.style.display = 'none';
  }
}

/* ------------------------------------------------------------ 4. 任务页渲染 */
function renderCollab(){
  var todo = arr(state.todoApprovals);
  var mine = arr(state.approvals);
  var dept = arr(state.deptOrders);
  var cc = arr(state.ccApprovals);
  var sch = scheduleItems();

  setEm('oaRailTask', todo.length);
  setEm('oaRailProj', projectGroups(mine, dept).length);
  setEm('oaRailAppr', todo.length + mine.length);
  setEm('oaRailSch', sch.length);

  document.querySelectorAll('#oaRail .rail-item').forEach(function(r){
    r.classList.toggle('on', r.dataset.panel === S.rail);
  });
  document.querySelectorAll('#v-collab .panel').forEach(function(p){
    p.classList.toggle('on', p.id === 'p-' + S.rail);
  });

  renderTaskPanel(todo);
  renderProjectPanel(mine, dept);
  renderApprovalPanel(todo, cc, mine, dept);
  renderSchedulePanel(sch);
}
function setEm(id, v){ var e = $o(id); if(e) e.textContent = String(n(v)); }

/* 任务面板：待我审批（双引擎合并结果，与经典「待办」同源） */
function renderTaskPanel(todo){
  var el = $o('p-tasks'); if(!el) return;
  if(!todo.length){ el.innerHTML = empty('暂无待我审批的任务'); return; }
  el.innerHTML = todo.slice(0, 30).map(function(a){
    return '<div class="task-card" data-appr="'+txt(a.id)+'" data-scope="todo">' +
      '<div class="task-line" style="margin-top:0">' + ic('stamp',17) +
        '<div class="tl-name truncate">'+txt(a.title || '审批单')+'</div>' + statusChip(a) + '</div>' +
      '<div class="tl-meta">'+ic('user',13)+txt(a.creatorName || a.applicantName || '—') +
        ' · '+txt(bizName(a.bizType))+' · '+txt(dt(a.createdAt))+'</div></div>';
  }).join('');
  bindApprovalRows(el);
}

/* 项目面板：后端无通用项目模块 ⇒ 按业务类型归集我的申请 + 本部门申请（口径标注在标题里） */
function projectGroups(mine, dept){
  var g = {};
  mine.forEach(function(a){ var k = bizName(a.bizType); (g[k] = g[k] || []).push(a); });
  dept.forEach(function(a){ var k = bizName(a.bizType); (g[k] = g[k] || []).push(a); });
  return Object.keys(g).map(function(k){ return {name:k, list:g[k]}; });
}
function renderProjectPanel(mine, dept){
  var el = $o('p-projects'); if(!el) return;
  var groups = projectGroups(mine, dept);
  if(!groups.length){ el.innerHTML = empty('暂无申请记录'); return; }
  el.innerHTML = '<div class="hintbar">'+ic('info')+
      '<div><b>按业务类型归集</b><div class="muted" style="margin-top:3px">'+
      '由「我发起的」与「本部门名义发起」合并，后端暂无独立项目模块</div></div></div>' +
    groups.map(function(g){
      var done = g.list.filter(function(a){ return a.status === 'APPROVED'; }).length;
      var pct = Math.round(done / g.list.length * 100);
      return '<div class="task-card"><div class="task-line" style="margin-top:0">'+
        '<div class="tl-name truncate">'+txt(g.name)+'</div>'+chip('prog', pct+'%')+'</div>'+
        '<div class="tl-meta">'+ic('task',13)+'共 '+g.list.length+' 单 · 已通过 '+done+
        ' · 待审 '+g.list.filter(function(a){return a.status==='PENDING';}).length+'</div></div>';
    }).join('');
}

/* 审批面板：四分段，计数与列表同源 */
function renderApprovalPanel(todo, cc, mine, dept){
  var el = $o('p-approvals'); if(!el) return;
  var scopes = [
    {k:'todo', t:'待我审批', list:todo},
    {k:'mine', t:'我发起的', list:mine},
    {k:'cc',   t:'抄送我的', list:cc},
    {k:'dept', t:'本部门',   list:dept}
  ];
  var cur = scopes.filter(function(x){ return x.k === S.apprScope; })[0] || scopes[0];
  el.innerHTML =
    '<div class="org-chips" style="margin-bottom:2px">' + scopes.map(function(x){
      return '<button class="org-chip'+(x.k === cur.k ? ' on' : '')+'" data-scope="'+x.k+'">'+
        txt(x.t)+' '+x.list.length+'</button>';
    }).join('') + '</div>' +
    (!cur.list.length ? empty('「'+cur.t+'」暂无记录') : cur.list.slice(0,40).map(function(a){
      return '<div class="task-card" data-appr="'+txt(a.id)+'" data-scope="'+cur.k+'">'+
        '<div class="task-line" style="margin-top:0">'+ic('stamp',17)+
          '<div class="tl-name truncate">'+txt(a.title || '审批单')+'</div>'+statusChip(a)+'</div>'+
        '<div class="tl-meta">'+ic('user',13)+txt(a.creatorName || a.applicantName || '—')+
        ' · '+txt(bizName(a.bizType))+' · '+txt(dt(a.createdAt))+
        (cur.k === 'dept' ? ' · 本部门名义' : '')+
        (cur.k === 'cc' ? (a.read ? ' · 已阅' : ' · 未读') : '')+'</div></div>';
    }).join(''));
  el.querySelectorAll('[data-scope]').forEach(function(b){
    if(b.classList.contains('org-chip')) b.onclick = function(){ S.apprScope = b.dataset.scope; oaRender(); };
  });
  bindApprovalRows(el);
}

/* 审批行点击 → OA 内详情页（不跳经典形态） */
function bindApprovalRows(root){
  root.querySelectorAll('[data-appr]').forEach(function(row){
    row.style.cursor = 'pointer';
    row.onclick = function(){ oaOpenApproval(row.dataset.appr, row.dataset.scope); };
  });
}

function oaOpenApproval(id, scope){
  // 必须转数字：既有 findApproval 用严格相等 a.id===id 匹配（经典页一律传数字
  // 字面量 / +dataset 转换），而 DOM 的 dataset 恒为字符串 ⇒ 不转必然「审批单不存在」。
  id = Number(id);
  var a = findApproval(id, scope);
  if(!a){ toast('审批单不存在或已刷新'); return; }
  S.apprDetail = {id:id, scope:scope};
  state.todoDetail = {id:id, scope:scope};   // 复用既有弹层与决策链路所需的上下文
  // 知会点开即置已读（与经典 openTodoDetail 同一行为，幂等）
  if(scope === 'cc' && a.read !== true && a.taskId && typeof markCcReadLocal === 'function') markCcReadLocal(a);
  oaGo('appr');
}

function renderApprDetail(){
  var d = S.apprDetail; var el = $o('v-appr');
  if(!el) return;
  if(!d){ el.innerHTML = empty('请选择一条审批记录'); return; }
  var a = findApproval(d.id, d.scope);
  if(!a){ el.innerHTML = empty('审批单已被刷新，请返回重进'); return; }
  var cur = (typeof currentNode === 'function') ? currentNode(a) : null;
  var flow = (typeof renderTimeline === 'function') ? renderTimeline(a) : '';
  var extra = (typeof renderApprovalDetailExtra === 'function') ? renderApprovalDetailExtra(a) : '';
  var canDecide = (d.scope === 'todo' && a.status === 'PENDING' && state.canApprove);

  el.innerHTML =
    '<div class="card" style="margin-top:12px">' +
      '<div class="sec-title" style="margin-bottom:6px">'+txt(a.title || '审批详情')+
        '<span class="more">'+statusChip(a)+'</span></div>' +
      '<div class="muted" style="line-height:1.85;margin-bottom:10px">' +
        '发起人：'+txt(a.creatorName || a.applicantName || '—')+'<br>' +
        '类型：'+txt(bizName(a.bizType))+'<br>' +
        '提交时间：'+txt(dt(a.createdAt)) +
        (a.decidedAt ? '<br>审批时间：'+txt(dt(a.decidedAt)) : '') +
        (a.status === 'PENDING' && cur
          ? '<br>当前流转到：<b>'+txt(cur.approverName || '—')+'</b>（'+
            txt(typeof approverTypeLabel === 'function' ? approverTypeLabel(cur.approverType) : cur.approverType)+
            '，第 '+n(cur.seq)+'/'+n(a.totalNodes || arr(a.timeline).length)+' 级）'
          : '') +
        (d.scope === 'cc' ? '<br><b>抄送知会</b>：无需你审批，仅供知悉与督办' : '') +
        (d.scope === 'dept' ? '<br><b>本部门名义发起</b>：可见与督办，决策由审批人处理' : '') +
      '</div>' +
      (flow ? '<div class="sec-title" style="margin-bottom:6px">流转路径</div>'+flow : '') +
      '<div class="sec-title" style="margin:10px 0 6px">正文</div>' +
      '<div style="font-size:12.5px;line-height:1.85;white-space:pre-wrap">'+txt(a.content || '（无正文）')+'</div>' +
      (extra ? '<div style="margin-top:12px;padding-top:10px;border-top:1px dashed var(--border)">'+extra+'</div>' : '') +
      (a.status !== 'PENDING'
        ? '<div style="margin-top:12px;padding-top:10px;border-top:1px dashed var(--border)">'+
          '<div class="sec-title" style="margin-bottom:4px">审批意见</div>'+
          '<div class="muted">'+txt(a.decisionNote || '（未填写意见）')+'</div></div>' : '') +
    '</div>' +
    (canDecide
      ? '<div style="display:flex;gap:8px;margin-top:12px">'+
          '<button class="sheet-cancel" style="flex:1" id="oaApBack">返回</button>'+
          '<button class="sheet-cancel" style="flex:1;border-color:var(--red);color:var(--red)" id="oaApRej">驳回</button>'+
          '<button class="sheet-cancel" style="flex:1;background:var(--brand);border-color:var(--brand);color:#fff" id="oaApOk">通过</button>'+
        '</div>'
      : '<div style="margin-top:12px"><button class="sheet-cancel" id="oaApBack">返回列表</button></div>');

  var back = $o('oaApBack'); if(back) back.onclick = function(){ oaGo(S.from || 'collab'); };
  var ok = $o('oaApOk');
  if(ok) ok.onclick = function(){
    // 决策走既有链路：askApprovalNote → commitApprovalDecision（双引擎分流的唯一判定点）
    askApprovalNote('APPROVE');
  };
  var rej = $o('oaApRej');
  if(rej) rej.onclick = function(){ askApprovalNote('REJECT'); };
}

/* 日程：两个真实日期字段合并（请假起止 + 数字员工排班）。
   审批单不进日程 —— approval_order 无 due/deadline 列，拿 createdAt 当日程是伪造语义。 */
function scheduleItems(){
  var out = [];
  arr(S.leave).forEach(function(l){
    if(l.startDate) out.push({time:day(l.startDate), body:'请假开始 · '+bizName(l.leaveTypeCode || 'LEAVE'),
      meta:'至 '+day(l.endDate)+'（'+n(l.days)+' 天）', mute:l.status !== 'APPROVED', src:'leave'});
    if(l.endDate) out.push({time:day(l.endDate), body:'请假结束 · 返岗',
      meta:'单据状态 '+txt(l.status || '—'), mute:true, src:'leave'});
  });
  arr(state.workers).forEach(function(w){
    if(!w.scheduleTime) return;
    out.push({time:w.scheduleTime, body:(w.name || '数字员工')+' 定时执行',
      meta:'每日 · '+(w.on ? '已启用' : '已停用')+' · 上次 '+(w.lastRunAt ? dt(w.lastRunAt) : '未执行'),
      mute:!w.on, src:'worker'});
  });
  out.sort(function(a, b){ return String(a.time).localeCompare(String(b.time)); });
  return out;
}
function renderSchedulePanel(sch){
  var el = $o('p-schedule'); if(!el) return;
  if(!sch.length){ el.innerHTML = empty('暂无由请假与排班合成的日程'); return; }
  el.innerHTML = '<div class="hintbar">'+ic('info')+
      '<div><b>日程口径</b><div class="muted" style="margin-top:3px">'+
      '由「我的请假起止日期」与「数字员工排班时刻」合成；审批单无截止字段，不计入</div></div></div>' +
    '<div class="task-card"><div class="tl">' + sch.slice(0, 40).map(function(x){
      return '<div class="tl-item'+(x.mute ? ' mute' : '')+'">'+
        '<div class="tl-time">'+txt(x.time)+'</div>'+
        '<div class="tl-body">'+txt(x.body)+'</div>'+
        '<div class="tl-meta">'+(x.src === 'worker' ? ic('clock',13) : ic('cal',13))+txt(x.meta)+'</div></div>';
    }).join('') + '</div></div>';
}

/* ---------------------------------------------------------- 5. 知识库页面 */
function renderKb(){
  var docs = arr(state.kbDocs);
  var grid = $o('oaKbGrid');
  if(grid){
    var ready = docs.filter(function(d){ return d.state === 'READY'; }).length;
    var proc  = docs.filter(function(d){ return d.state && d.state !== 'READY' && d.state !== 'FAILED'; }).length;
    var chunks = docs.reduce(function(s, d){ return s + n(d.chunkCount); }, 0);
    grid.innerHTML = [
      ['folder','我的文档', docs.length],
      ['check-circle','已就绪', ready],
      ['clock','处理中', proc],
      ['db','总切片', chunks]
    ].map(function(x, i){
      return '<div class="kb-tile'+(i === 1 ? ' kb-blue' : (i === 3 ? ' kb-amber' : ''))+'">'+
        ic(x[0],26)+'<span>'+x[1]+'</span>'+
        '<b class="num" style="font-size:15px;margin-top:3px">'+x[2]+'</b></div>';
    }).join('');
  }
  var list = $o('oaKbList'); if(!list) return;
  if(!docs.length){ list.innerHTML = empty('知识库还没有文档，点右上「上传文档」'); return; }
  list.innerHTML = docs.slice(0, 30).map(function(d){
    var st = d.state === 'READY' ? chip('due','已就绪')
           : (d.state === 'FAILED' ? chip('rej','失败') : chip('wait', d.state || '处理中'));
    // 后端 KbService.guessIcon 的词表精确为 {doc, sheet, pdf, file} —— 没有 'xls'。
    // 色块按该词表映射（表格=绿 xls、PDF=青 pdf、其余=蓝 doc），
    // 字形只在 i-sheet 存在时替换（i-pdf / i-file 未定义，用 doc 字形兜底，避免空白图标）。
    var icoCls = d.icon === 'sheet' ? 'xls' : (d.icon === 'pdf' ? 'pdf' : 'doc');
    var icoGlyph = d.icon === 'sheet' ? 'sheet' : 'doc';
    return '<div class="lrow">'+
      '<div class="file-ico '+icoCls+'">'+
        ic(icoGlyph, 18)+'</div>'+
      '<div class="txt"><div class="t1 truncate">'+txt(d.name)+'</div>'+
      // scope 是大写枚举（DocView 默认 "PERSONAL"；经典页亦用 === 'TENANT' 判定）
      '<div class="t2">'+txt(d.scope === 'TENANT' ? '企业知识库' : '我的知识库')+
        ' · '+n(d.chunkCount)+' 切片 · '+txt((d.sizeBytes ? Math.max(1, Math.round(n(d.sizeBytes)/1024))+' KB' : '—'))+
        ' · '+txt(dt(d.createdAt))+'</div></div>'+ st +'</div>';
  }).join('');
}

/* ------------------------------------------------------ 6. 部门 / 通讯录页面 */
function renderOrg(){
  var chips = $o('oaOrgChips');
  var o = S.org || {};
  var depts = arr(o.departments);
  if(chips){
    chips.innerHTML = '<button class="org-chip'+(S.deptId === null ? ' on' : '')+'" data-dept="">全部</button>' +
      depts.map(function(d){
        return '<button class="org-chip'+(String(S.deptId) === String(d.id) ? ' on' : '')+'" data-dept="'+txt(d.id)+'">'+
          txt(d.name)+'</button>';
      }).join('');
    chips.querySelectorAll('.org-chip').forEach(function(c){
      c.onclick = function(){
        S.deptId = c.dataset.dept ? Number(c.dataset.dept) : null;
        loadOrgMembers().then(renderOrg);
      };
    });
  }
  var list = $o('oaOrgList'); if(!list) return;
  var items = arr(o.members);
  var cnt = $o('oaOrgCnt');
  if(cnt) cnt.textContent = items.length ? ('共 '+n(o.total || items.length)+' 人') : '';
  if(!items.length){ list.innerHTML = empty('暂无可见成员（无机构归属时后端返回空列表）'); return; }
  list.innerHTML = items.map(function(m){
    var name = m.name || m.username || '—';
    return '<div class="contact-card"><div class="contact-row">'+
      '<div class="cava" style="display:flex;align-items:center;justify-content:center;'+
        'font-weight:700;font-size:17px;color:#fff;'+
        'background:linear-gradient(140deg,var(--brand),var(--brand-dark))">'+txt(name.slice(0,1))+'</div>'+
      '<div class="cmeta">'+
        '<div class="cname">'+txt(name)+
          (m.jobTitle ? ' <span class="sep">|</span> '+txt(m.jobTitle) : '')+
          (m.isOrgAdmin ? ' '+chip('prog','组织管理员') : '')+'</div>'+
        '<div class="cact">'+txt(m.departmentName || '未分配部门')+
          (m.employeeNo ? ' · 工号 '+txt(m.employeeNo) : '')+
          // 手机号 / 邮箱默认隐藏：接口对普通成员也返回，但「可读」不等于「应当默认可见」
          '<button class="cact-reveal" data-reveal="'+txt(m.id)+'">查看联系方式</button>'+
          '<span id="oac-'+txt(m.id)+'"></span>'+
        '</div>'+
      '</div></div></div>';
  }).join('');
  list.querySelectorAll('[data-reveal]').forEach(function(b){
    b.onclick = function(){
      var m = items.filter(function(x){ return String(x.id) === b.dataset.reveal; })[0] || {};
      var box = $o('oac-' + b.dataset.reveal);
      if(!box) return;
      box.textContent = ' · ' + (m.mobile || '无手机号') + ' · ' + (m.email || '无邮箱');
      b.style.display = 'none';    // 只在本次会话展开，不写任何本地存储
    };
  });
}

async function loadOrgMembers(){
  var q = S.orgQ ? ('?keyword=' + encodeURIComponent(S.orgQ)) : '';
  var dq = S.deptId ? ((q ? q + '&' : '?') + 'departmentId=' + S.deptId) : '';
  var res = await API.req('/v1/org/members' + q + dq);
  S.org = S.org || {};
  S.org.members = arr(res && res.items ? res.items : res);
  S.org.total = res && res.total;
}
async function loadOrgAll(){
  S.org = S.org || {};
  var r = await Promise.all([
    API.req('/v1/org/departments').catch(function(){ return []; }),
    API.req('/v1/org/profile').catch(function(){ return null; }),
    loadOrgMembers().catch(function(){})
  ]);
  // /v1/org/departments 返回的是对象 {total,maxDepth,depthLimit,flat,tree}，
  // 既不是数组、也不是 {items}；直接 arr() 只会得到空数组 ⇒ 部门筛选器一个都渲染不出来
  // （接口支持但界面上配不出来 = 能力事实上不可用）。取 flat 作为筛选器数据源。
  var d0 = r[0] || {};
  S.org.departments = arr(d0.flat || d0.tree || d0);
  S.org.profile = r[1];
  return S.org;
}

/* --------------------------------------------------------------- 7. 我的页面 */
function renderMe(){
  var u = state.user || {};
  var name = u.nickname || u.username || '—';
  var ms = state.myStats || {};
  var ava = $o('oaMeAva'), nm = $o('oaMeName'), rl = $o('oaMeRole');
  if(ava) ava.textContent = String(name).slice(0, 1);
  if(nm) nm.textContent = name;
  if(rl) rl.textContent = (typeof workerRoleText === 'function' ? workerRoleText(u.roles || []) : '') +
    (u.username ? ' | ' + u.username : '');

  var data = $o('oaMeData');
  if(data){
    data.innerHTML = [
      ['待办', n(arr(state.todoApprovals).length)],
      ['审批', n(has(ms.myApplications) ? ms.myApplications : arr(state.approvals).length)],
      ['会话', n(has(ms.conversations) ? ms.conversations : 0)],
      ['知识库', n(has(ms.kbDocs) ? ms.kbDocs : arr(state.kbDocs).length)]
    ].map(function(x){ return '<div><b>'+x[1]+'</b><span>'+x[0]+'</span></div>'; }).join('');
  }
  var acts = $o('oaMeActions');
  if(acts){
    /* 4 个入口一律 OA 内跳转。原来它们写的是「打开经典工作台页面」并真的切回老版 ——
       在新版里点任意一条就被弹出新版，与「所有页面跳转都在新版内」冲突。 */
    var links = [
      ['wallet','额度与账单','bill','查看剩余额度与用量流水'],
      ['log','我的操作记录','log','查看账号操作留痕'],
      ['shield','权限申请','perm','申请与查看已持有的权限'],
      ['megaphone','投诉与建议','feedback','提交反馈、查看答复']
    ];
    acts.innerHTML = links.map(function(l){
      return '<div class="lrow" data-view="'+l[2]+'">'+ic(l[0])+
        '<div class="txt"><div class="t1">'+l[1]+'</div>'+
        '<div class="t2">'+l[3]+'</div></div>'+ic('chevron')+'</div>';
    }).join('') +
    '<div class="lrow" id="oaMeLogout">'+ic('logout')+
      '<div class="txt"><div class="t1" style="color:var(--red)">退出登录</div></div>'+ic('chevron')+'</div>';
    acts.querySelectorAll('[data-view]').forEach(function(r){
      r.style.cursor = 'pointer';
      r.onclick = function(){ oaGo(r.dataset.view); };
    });
    var lo = $o('oaMeLogout');
    if(lo){ lo.style.cursor = 'pointer'; lo.onclick = function(){ doLogout(); resetMode(); }; }
  }
}

/* ------------------------------- 7.5 我的 · 账户四个内页（全部在新版内完成）
   这四项原先调 oaGoClassic() 切回经典形态 —— 在新版里点一下就被弹出新版。
   现在改为 OA 内视图。三条纪律：
   ① 事实口径一律复用经典形态抽出的纯函数（quotaNumbers / billTokens / billSourceLabel /
      logIsOk / logStatusLabel / logActionText / fbRouteLine / fbInboxPending / permStatusText /
      permStatusClass / permPathText），本层不再重新解释一次账本、留痕、权限或反馈路由；
   ② 动作复用经典形态的既有函数（applyPermission / revokePermission / exportBill / fbSubmitToast），
      表单口径不复制；
   ③ 徽标只有「皮肤」不同（经典 .badge → OA .chip），文案仍取上面那些函数。
   ---------------------------------------------------------------------------- */
/* 千分位：复用经典形态的 fmt；缺失时退化为原值，不静默变成 NaN */
function qn(v){ return (typeof fmt === 'function') ? fmt(v) : String(v == null ? 0 : v); }
/* 经典徽标类 → OA 徽标类（同一语义两套皮肤，文案不在此处另写） */
var CHIP_OF_BADGE = {wait:'wait', ok:'due', danger:'rej', off:'done', go:'prog'};
function badgeChip(cls, text){ return chip(CHIP_OF_BADGE[cls] || 'done', text); }

/* ① 额度与账单 */
function renderOaBill(){
  var q = $o('oaBillQuota');
  if(q){
    var nums = (typeof quotaNumbers === 'function') ? quotaNumbers() : {total:0, left:0, usedPct:0};
    q.innerHTML =
      '<div class="sec-title" style="margin-top:0">剩余额度</div>' +
      '<div style="display:flex;align-items:baseline;gap:8px">' +
        '<span class="num" style="font-size:26px;font-weight:700">' + qn(nums.left) + '</span>' +
        '<span class="muted">/ ' + qn(nums.total) + ' 词元（本月套餐）</span>' +
      '</div>' +
      '<div style="height:6px;border-radius:var(--r-full);background:var(--surface-3);overflow:hidden;margin-top:10px">' +
        '<i style="display:block;height:100%;width:' + n(nums.usedPct) + '%;background:' +
        (nums.usedPct >= 85 ? 'var(--red)' : 'var(--brand)') + '"></i>' +
      '</div>' +
      '<div class="muted" style="margin-top:7px">已用 ' + n(nums.usedPct) + '%' +
        (nums.usedPct >= 85 ? ' · 额度偏低，可在首页让我帮你申请扩容' : '') + '</div>';
  }
  var box = $o('oaBillList');
  if(box){
    var list = arr(state.bill);
    var cnt = $o('oaBillCnt');
    if(cnt) cnt.textContent = list.length ? ('最近 ' + Math.min(list.length, 20) + ' 条') : '';
    box.innerHTML = list.length
      ? list.slice(0, 20).map(function(b){
          return '<div class="lrow">' + ic('wallet') +
            '<div class="txt"><div class="t1">' + txt(billSourceLabel(b)) + '</div>' +
            '<div class="t2">' + txt(dt(b.createdAt)) + '</div></div>' +
            '<span class="num" style="font-weight:700">+' + qn(billTokens(b)) + '</span></div>';
        }).join('')
      : empty('本月还没有用量记录');
  }
}

/* ② 我的操作记录 */
function renderOaLog(){
  var box = $o('oaLogList'); if(!box) return;
  var list = arr(state.log);
  var cnt = $o('oaLogCnt');
  if(cnt) cnt.textContent = list.length ? ('共 ' + list.length + ' 条') : '';
  box.innerHTML = list.length
    ? list.slice(0, 20).map(function(l){
        return '<div class="lrow">' + ic('log') +
          '<div class="txt"><div class="t1">' + txt(logActionText(l)) + '</div>' +
          '<div class="t2">' + txt(dt(l.createdAt)) + '</div></div>' +
          chip(logIsOk(l) ? 'due' : 'rej', logStatusLabel(l)) + '</div>';
      }).join('')
    : empty('暂无操作记录');
}

/* ③ 权限申请：可申请 / 我已持有 / 我的申请（申请与回收走经典形态同一入口） */
function renderOaPerm(){
  var cbox = $o('oaPermCatalog');
  if(cbox){
    var items = arr((state.permCatalog || {}).items);
    cbox.innerHTML = items.length
      ? items.map(function(it){
          var right;
          if(it.held) right = chip('due','已持有');
          else if(it.pending) right = chip('wait','审批中');
          else right = '<button type="button" class="btn small" data-apply="' +
            txt(it.permissionCode) + '">申请</button>';
          return '<div class="lrow">' + ic('shield') +
            '<div class="txt"><div class="t1">' + txt(it.permissionName || it.permissionCode) + '</div>' +
            '<div class="t2">' + txt(it.permissionCode) +
              (it.workerType ? ' · 用于 ' + txt(it.workerType) : '') +
              ' · 审批角色：' + txt(it.requiredRoles || '—') + '</div></div>' + right + '</div>';
        }).join('')
      : '<div class="muted" style="padding:4px 0">暂无可申请的权限项</div>';
    cbox.querySelectorAll('[data-apply]').forEach(function(b){
      b.onclick = function(){ applyPermission(b.dataset.apply); };
    });
  }

  var hbox = $o('oaPermHold');
  if(hbox){
    var holds = arr(state.permHoldings);
    hbox.innerHTML = holds.length
      ? holds.map(function(h){
          var src = h.byGrant ? (h.byRole ? '角色 + 授权' : '授权发放') : '角色内置';
          var exp = h.expireAt ? (' · 到期 ' + txt(String(h.expireAt).slice(0,10))) : '';
          var btn = (h.byGrant && h.grantId)
            ? '<button type="button" class="btn ghost small" data-revoke="' + txt(h.grantId) + '">回收</button>'
            : '<span class="muted">有效</span>';
          return '<div class="lrow">' + ic('check') +
            '<div class="txt"><div class="t1">' + txt(h.permissionName || h.permissionCode) + '</div>' +
            '<div class="t2">' + txt(src) + exp + '</div></div>' + btn + '</div>';
        }).join('')
      : '<div class="muted" style="padding:4px 0">暂无额外权限；通用能力（对话 / 知识库检索 / 创建数字员工）默认已开通</div>';
    hbox.querySelectorAll('[data-revoke]').forEach(function(b){
      // dataset 是字符串；经典入口按数字 id 比对，这里必须转回数字
      b.onclick = function(){ revokePermission(Number(b.dataset.revoke)); };
    });
  }

  var mbox = $o('oaPermMine');
  if(mbox){
    var grants = arr(state.permGrants);
    mbox.innerHTML = grants.length
      ? grants.map(function(g){
          var note = g.auditNote ? '<div class="t2">意见：' + txt(g.auditNote) + '</div>' : '';
          var dept = (g.applicantType === 'DEPARTMENT')
            ? (' ' + chip('prog','部门申请')) : '';
          return '<div class="lrow">' + ic('log') +
            '<div class="txt"><div class="t1">' + txt(g.permissionName || g.permissionCode) + ' ' +
              badgeChip(permStatusClass(g.status), permStatusText(g.status)) + dept + '</div>' +
            '<div class="t2">' + txt(permPathText(g)) + '</div>' + note + '</div></div>';
        }).join('')
      : '<div class="muted" style="padding:4px 0">还没有提交过权限申请</div>';
  }
}

/* ④ 投诉与建议：路由说明 + 表单 + 收到的建议 + 我的提交。
   条目渲染复用经典形态的 fbItemHtml（id 前缀 oaFb，避免与经典同名 id 相撞）。 */
function renderOaFbCats(){
  var box = $o('oaFbCats'); if(!box) return;
  var cats = (typeof FB_CATS === 'undefined') ? [] : FB_CATS;
  var cur = state.fbCat || 'ADVICE';
  box.innerHTML = cats.map(function(c){
    return '<span class="fb-cat' + (cur === c[0] ? ' on' : '') + '" data-cat="' + txt(c[0]) + '">' +
      txt(c[1]) + '</span>';
  }).join('');
  box.querySelectorAll('[data-cat]').forEach(function(el){
    el.onclick = function(){
      // state.fbCat 是唯一选择状态（经典表单也用同一个），两侧一起重画
      state.fbCat = el.dataset.cat || 'ADVICE';
      if(typeof renderFbCats === 'function') renderFbCats();
      renderOaFbCats();
    };
  });
}
function oaFbCount(){
  var el = $o('oaFbContent'), cnt = $o('oaFbCount');
  if(el && cnt) cnt.textContent = el.value.length + ' / 2000';
}
function oaSubmitFeedback(){
  var el = $o('oaFbContent');
  var content = ((el && el.value) || '').trim();
  if(!content){ toast('请先填写反馈内容'); return; }
  var btn = $o('oaFbSubmit');
  if(btn) btn.disabled = true;
  API.feedbackSubmit({
    category: state.fbCat || 'ADVICE',
    content: content,
    contact: ((($o('oaFbContact') || {}).value) || '').trim() || null,
    anonymous: !!(($o('oaFbAnonymous') || {}).checked)
  }).then(function(r){
    if(typeof fbSubmitToast === 'function') fbSubmitToast(r);
    el.value = ''; oaFbCount();
    var c = $o('oaFbContact'); if(c) c.value = '';
    var a = $o('oaFbAnonymous'); if(a) a.checked = false;
    return (typeof reloadFeedback === 'function') ? reloadFeedback() : null;
  }).then(function(){
    renderOaFeedback();
  }).catch(function(e){
    toast('提交失败：' + (e && e.message ? e.message : '后端异常'));
  }).then(function(){
    if(btn) btn.disabled = false;
  });
}
/* 只重画「数据驱动的部分」——表单里用户正在输入的内容一律不碰 */
function renderOaFeedback(){
  var route = $o('oaFbRoute');
  if(route) route.innerHTML = (typeof fbRouteLine === 'function') ? fbRouteLine() : '';
  renderOaFbCats();
  var inbox = $o('oaFbInbox');
  if(inbox){
    var items = (state.fbInbox && arr(state.fbInbox.items)) || [];
    var icnt = $o('oaFbInboxCnt');
    if(icnt) icnt.textContent = items.length
      ? ('待处理 ' + ((typeof fbInboxPending === 'function') ? fbInboxPending() : 0) + ' / 共 ' + items.length + ' 条')
      : '';
    inbox.innerHTML = items.length
      ? items.map(function(f){ return fbItemHtml(f, true, 'oaFb'); }).join('')
      : empty('暂无收到的建议');
  }
  var mine = $o('oaFbMine');
  if(mine){
    var mi = (state.fbMine && arr(state.fbMine.items)) || [];
    var mcnt = $o('oaFbMineCnt');
    if(mcnt) mcnt.textContent = mi.length
      ? ('共 ' + mi.length + ' 条，待处理 ' + ((state.fbMine && state.fbMine.pending) || 0) + ' 条')
      : '';
    mine.innerHTML = mi.length
      ? mi.map(function(f){ return fbItemHtml(f, false, 'oaFb'); }).join('')
      : '<div class="muted" style="padding:4px 0">还没有提交过反馈</div>';
  }
}

/* ------------------------------------------- 8. 数字员工 / 专家 / 定时 / 技能 */
function renderWorkers(){
  var el = $o('oaWorkersList'); if(!el) return;
  var ws = arr(state.workers);
  if(!ws.length){ el.innerHTML = empty('暂无可用数字员工'); return; }
  el.innerHTML = ws.map(function(w){
    var on = w.on ? chip('prog', w.scheduleTime ? ('定时 ' + w.scheduleTime) : '在线') : chip('done','未启用');
    return '<div class="lrow" data-worker="'+txt(w.id)+'">'+
      '<div class="ava brand" style="display:flex;align-items:center;justify-content:center">'+ic('bot',18)+'</div>'+
      '<div class="txt"><div class="t1 truncate">'+txt(w.name || '数字员工')+' '+on+'</div>'+
      '<div class="t2 truncate">'+txt(w.roleName || w.description || w.duty || '数字员工')+'</div></div>'+
      ic('chevron')+'</div>';
  }).join('');
  el.querySelectorAll('[data-worker]').forEach(function(r){
    r.style.cursor = 'pointer';
    r.onclick = function(){
      var w = ws.filter(function(x){ return String(x.id) === r.dataset.worker; })[0];
      oaPickWorker(w);
    };
  });
}
function renderExperts(){
  var el = $o('oaExpertsList'); if(!el) return;
  var xs = arr(state.experts);
  if(!xs.length){ el.innerHTML = empty('暂无可用专家'); return; }
  el.innerHTML = xs.map(function(e){
    return '<div class="lrow" data-expert="'+txt(e.key || e.id)+'">'+
      '<div class="ava" style="display:flex;align-items:center;justify-content:center">'+
        ic(typeof iconKey === 'function' ? iconKey(e.icon) : 'target',18)+'</div>'+
      '<div class="txt"><div class="t1 truncate">'+txt(e.name || e.key)+'</div>'+
      '<div class="t2 truncate">'+txt(e.desc || e.intro || '领域专家')+'</div></div>'+
      ic('chevron')+'</div>';
  }).join('');
  el.querySelectorAll('[data-expert]').forEach(function(r){
    r.style.cursor = 'pointer';
    r.onclick = function(){
      var e = xs.filter(function(x){ return String(x.key || x.id) === r.dataset.expert; })[0];
      oaPickExpert(e);
    };
  });
}

function renderTimers(){
  var el = $o('oaTimersList'); if(!el) return;
  var ws = arr(state.workers).filter(function(w){ return has(w.scheduleTime); });
  if(!ws.length){
    el.innerHTML = empty('暂无配置执行时刻的数字员工') +
      '<div class="hintbar" style="margin-top:10px">'+ic('info')+
      '<div><b>怎么配置</b><div class="muted" style="margin-top:3px">'+
      '在「专家与员工」（经典形态）里给数字员工设置执行时刻后，会在此按点到点执行</div></div></div>';
    return;
  }
  el.innerHTML = ws.map(function(w){
    return '<div class="task-card">'+
      '<div class="task-head"><div class="ava brand" style="display:flex;align-items:center;justify-content:center">'+ic('bot',17)+'</div>'+
        '<div class="who"><b>'+txt(w.name || '数字员工')+'</b>'+
        '<span>每日 '+txt(w.scheduleTime)+' · '+(w.on ? '已启用' : '已停用')+
        ' · 上次 '+(w.lastRunAt ? txt(dt(w.lastRunAt)) : '未执行')+'</span></div>'+
        (w.on ? chip('prog','运行中') : chip('done','已停用'))+'</div>'+
      '<div class="task-line">'+ic('clock',17)+
        '<div class="tl-name">'+txt(w.taskPrompt ? String(w.taskPrompt).slice(0,26) : '（未设置任务内容）')+'</div></div>'+
      '<div style="display:flex;gap:8px;margin-top:10px">'+
        '<button class="icon-act" data-run="'+txt(w.id)+'">立即执行</button>'+
        '<button class="icon-act" data-time="'+txt(w.id)+'">改执行时刻</button>'+
        '<button class="icon-act" data-runs="'+txt(w.id)+'">执行记录</button>'+
      '</div>'+
      '<div id="oar-'+txt(w.id)+'"></div>'+
    '</div>';
  }).join('');

  el.querySelectorAll('[data-run]').forEach(function(b){
    b.onclick = function(){ oaRunWorkerNow(Number(b.dataset.run), b); };
  });
  el.querySelectorAll('[data-time]').forEach(function(b){
    b.onclick = function(){ oaChangeSchedule(Number(b.dataset.time)); };
  });
  el.querySelectorAll('[data-runs]').forEach(function(b){
    b.onclick = function(){ oaShowRuns(Number(b.dataset.runs)); };
  });
}

async function oaRunWorkerNow(id, btn){
  if(!id) return;
  var old = btn.textContent; btn.disabled = true; btn.textContent = '执行中…';
  try{
    var r = await API.runWorkerNow(id);
    toast('已触发执行' + (r && r.id ? '（记录 #' + r.id + '）' : ''));
    try{ state.workers = arr(await API.workers()); }catch(e){}
    oaShowRuns(id);
    try{ await refreshShared(); }catch(e){}
    renderTimers();
  }catch(e){
    toast('执行失败：' + (e.message || '未知错误'));
    btn.disabled = false; btn.textContent = old;
  }
}
function oaChangeSchedule(id){
  var w = arr(state.workers).filter(function(x){ return x.id === id; })[0] || {};
  askDialog({
    title:'修改执行时刻', mode:'input', message:'每日执行时刻（24 小时制 HH:mm）',
    placeholder:'例如 09:00', value:w.scheduleTime || '', required:true,
    presets:['08:00','09:00','12:00','18:00'],
    onOk: async function(v){
      if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(String(v || '').trim())){ toast('格式应为 HH:mm'); return; }
      try{
        await API.updateWorker(id, Object.assign({}, w, {scheduleTime:String(v).trim()}));
        toast('已更新为每日 ' + String(v).trim());
        state.workers = arr(await API.workers());
        renderTimers();
      }catch(e){ toast('更新失败：' + (e.message || '未知错误')); }
    }
  });
}
async function oaShowRuns(id){
  var box = $o('oar-' + id); if(!box) return;
  box.innerHTML = '<div class="muted" style="margin-top:9px">加载执行记录…</div>';
  try{
    var runs = arr(await API.workerRuns(id));
    if(!runs.length){ box.innerHTML = '<div class="muted" style="margin-top:9px">暂无执行记录</div>'; return; }
    box.innerHTML = '<div class="tl" style="margin-top:10px">' + runs.slice(0, 8).map(function(r){
      var ok = !r.errorMsg;
      return '<div class="tl-item'+(ok ? '' : ' mute')+'">'+
        '<div class="tl-time">'+txt(dt(r.startedAt))+'</div>'+
        '<div class="tl-body">'+txt(r.triggerType === 'SCHEDULE' ? '定时触发' : '手动触发')+
          ' · '+(ok ? '成功' : '失败')+'</div>'+
        '<div class="tl-meta">'+ic('doc',13)+txt(r.output ? String(r.output).slice(0,60) : (r.errorMsg || '（无产出）'))+'</div></div>';
    }).join('') + '</div>';
  }catch(e){
    box.innerHTML = '<div class="muted" style="margin-top:9px">执行记录读取失败：'+txt(e.message || '')+'</div>';
  }
}

function renderSkills(){
  var el = $o('oaSkillsList'); if(!el) return;
  var ks = arr(state.skills);
  if(!ks.length){ el.innerHTML = empty('暂无可用技能'); return; }
  el.innerHTML = ks.map(function(k){
    return '<div class="lrow">'+
      '<div class="ava" style="display:flex;align-items:center;justify-content:center">'+
        ic(typeof iconKey === 'function' ? iconKey(k.icon) : 'puzzle',18)+'</div>'+
      '<div class="txt"><div class="t1 truncate">'+txt(k.name || k.key)+'</div>'+
      '<div class="t2 truncate">'+txt(k.description || k.desc || '')+'</div></div></div>';
  }).join('');
}

function renderRecent(){
  var el = $o('oaRecentList'); if(!el) return;
  var cs = arr(state.conversations);
  if(!cs.length){ el.innerHTML = empty('暂无历史会话'); return; }
  el.innerHTML = cs.slice(0, 30).map(function(c){
    return '<div class="lrow" data-conv="'+txt(c.id)+'">'+ic('chat')+
      '<div class="txt"><div class="t1 truncate">'+txt(c.title || ('会话 #' + c.id))+'</div>'+
      '<div class="t2">'+txt(dt(c.lastMsgAt || c.createdAt))+'</div></div>'+ic('chevron')+'</div>';
  }).join('');
  el.querySelectorAll('[data-conv]').forEach(function(r){
    r.style.cursor = 'pointer';
    r.onclick = function(){ oaResumeConversation(Number(r.dataset.conv)); };
  });
}

/* ------------------------------------------------------------ 9. 对话坞（原地） */
function dockEl(){ return $o('oaDockList'); }

function oaSetChatting(on){
  var home = $o('v-home'); if(home) home.classList.toggle('chatting', !!on);
  if(on && $o('oaTag')) $o('oaTag').style.display = 'none';
}

/* 数字人回应新气泡：一次性点头，把「这条是冲着它说的」表达出来。
   必须先摘 class 并强制回流 —— 连续两条气泡沿用同一个 class 时动画不会重放。 */
var nodTimer = null;
function oaNodRobot(){
  if(!ROBOT) return;
  ROBOT.classList.remove('nod');
  void ROBOT.offsetWidth;
  ROBOT.classList.add('nod');
  if(nodTimer) clearTimeout(nodTimer);
  nodTimer = setTimeout(function(){ if(ROBOT) ROBOT.classList.remove('nod'); }, 520);
}

function oaPushBub(role, html, opts){
  var list = dockEl(); if(!list) return null;
  opts = opts || {};
  var el = document.createElement('div');
  el.className = 'bub ' + (role === 'user' ? 'me' : 'ai') + (opts.ans ? ' ans' : '');
  el.innerHTML = html + '<svg class="tail" viewBox="0 0 13 13" aria-hidden="true"><path d="M6.5 0.5 12.5 12.5 0.5 12.5z"/></svg>';
  list.appendChild(el);
  oaSetChatting(true);
  oaNodRobot();
  oaScrollDock();
  requestAnimationFrame(oaLayoutTails);
  return el;
}
function oaScrollDock(){ var l = dockEl(); if(l) l.scrollTop = l.scrollHeight; }

/* 气泡三角朝向：全部指向数字人锚点（用户口径「气泡三角都对着数字人」）。
   三角基准为「顶点朝上」，故旋转量 = 方向角 θ + 90°。
   落点 = 从气泡中心朝锚点发射的射线与气泡矩形边的交点（保证三角永远贴在边上）。
   视口窄也不例外 —— 之前 <360px 时退化成「恒朝正上方」，那就不再指向数字人了。
   量不到锚点（视图隐藏中、位图未解码）时写成「正上方居中」而不是不写：
   不写 = 停在 --tail-angle 的初始态 0deg，现象与「退化」相同但更隐蔽。 */
function oaLayoutTails(){
  var home = $o('v-home');
  if(!home || !home.classList.contains('chatting')) return;
  var anchor = ROBOT || home.querySelector('.robot-wrap');
  var ar = anchor ? anchor.getBoundingClientRect() : null;
  var A = (ar && ar.width && ar.height) ? {x:ar.left + ar.width/2, y:ar.top + ar.height/2} : null;
  home.querySelectorAll('.bub').forEach(function(b){
    var tail = b.querySelector('.tail'); if(!tail) return;
    var br = b.getBoundingClientRect();
    if(!br.width || !br.height) return;
    var hw = br.width/2, hh = br.height/2;
    var px = hw, py = 0, ang = 0;
    if(A){
      var dx = A.x - (br.left + hw), dy = A.y - (br.top + hh);
      if(Math.abs(dx) < 1 && Math.abs(dy) < 1){ dx = 0; dy = -1; }
      var th = Math.atan2(dy, dx);
      var ux = Math.cos(th), uy = Math.sin(th);
      var tx = Math.abs(ux) < 1e-6 ? Infinity : hw/Math.abs(ux);
      var ty = Math.abs(uy) < 1e-6 ? Infinity : hh/Math.abs(uy);
      var t = Math.min(tx, ty);
      if(isFinite(t)){ px = hw + ux*t; py = hh + uy*t; ang = th + Math.PI/2; }
    }
    tail.style.setProperty('--tail-x', px.toFixed(2) + 'px');
    tail.style.setProperty('--tail-y', py.toFixed(2) + 'px');
    tail.style.setProperty('--tail-angle', (ang*180/Math.PI).toFixed(2) + 'deg');
  });
}
document.addEventListener('scroll', function(){ oaLayoutTails(); }, true);
window.addEventListener('resize', oaLayoutTails);

/* 顶部标出当前对话对象：与 state.chatWorker 同形，但绑定在本层自己的会话上 */
function oaBanner(){
  var list = dockEl(); if(!list) return;
  var old = list.querySelector('.oa-who'); if(old) old.remove();
  if(!S.worker && !S.expert) return;
  var d = document.createElement('div');
  d.className = 'oa-who';
  d.style.cssText = 'align-self:center;font-size:11px;color:var(--text-3);margin:2px 0 4px';
  d.textContent = '与「' + (S.worker ? (S.worker.name || '数字员工') : S.expert.name) + '」对话中';
  list.insertBefore(d, list.firstChild);
}

function oaPickWorker(w){
  if(!w) return;
  S.worker = w; S.expert = null;
  oaGo('home');
  oaBanner();
  oaPushBub('ai', '已选择数字员工「'+txt(w.name || '数字员工')+'」'+
    (w.roleName ? '（职责：'+txt(w.roleName)+'）' : '')+'<div class="bub-meta">'+
    txt(w.scheduleTime ? '排班 ' + w.scheduleTime : '可随时对话')+'</div>');
  var i = $o('oaInput'); if(i) i.focus();
}
function oaPickExpert(e){
  if(!e) return;
  S.expert = e; S.worker = null;
  oaGo('home');
  oaBanner();
  oaPushBub('ai', '已选择专家「'+txt(e.name || e.key)+'」<div class="bub-meta">'+
    txt(e.description || '领域专家视角')+'</div>');
  var i = $o('oaInput'); if(i) i.focus();
}

async function oaEnsureConv(){
  if(S.convId) return S.convId;
  var title = (S.worker ? (S.worker.name || '数字员工') : (S.expert ? (S.expert.name || '专家') : '协同')) + ' · 对话';
  var c = await API.createConversation(title, 'aioa-client', S.worker ? S.worker.id : null);
  S.convId = c && (c.id || c.conversationId);
  if(!S.convId) throw new Error('会话创建失败');
  return S.convId;
}

async function oaSend(){
  var input = $o('oaInput'); if(!input) return;
  var q = String(input.value || '').trim();
  if(!q || S.busy) return;
  input.value = '';
  oaPushBub('user', txt(q));

  var bubble = oaPushBub('ai', '<span class="tx"><span class="typing"><i></i><i></i><i></i></span></span>');
  if(!bubble) return;
  // 流式文本必须写进 .tx —— 直接写 bubble.textContent 会把三角节点一起抹掉（三角会凭空消失）
  var tx = bubble.querySelector('.tx');
  S.busy = true;
  var stop = $o('oaStop'); if(stop) stop.style.display = '';
  var text = '';

  try{
    var convId = await oaEnsureConv();
    var run = await API.createRun(convId, q, {
      kb_on: (state.kbOn !== false),
      expert: S.expert ? (S.expert.name || S.expert.key) : undefined
    });
    var runId = run && (run.id || run.runId);
    // 与经典形态共用 state.runId：停止生成按钮只有一个真值来源
    state.runId = runId;
    S.controller = null;
    await API.stream(runId, {
      onStarted: function(p){
        if(!p || !p.model) return;
        var m = document.createElement('div');
        m.className = 'bub-meta';
        m.textContent = '模型：' + (typeof modelTier === 'function' ? modelTier(p.model) : p.model);
        bubble.appendChild(m);
      },
      onDelta: function(t){ text += t; tx.textContent = text; oaScrollDock(); oaLayoutTails(); },
      onUsage: function(u){
        if(!u) return;
        var m = document.createElement('div');
        m.className = 'bub-meta';
        m.textContent = '本次消耗 ' + fmt(u.total) + ' 词元（输入 ' + fmt(u.prompt) + ' / 输出 ' + fmt(u.completion) + '）';
        bubble.appendChild(m);
        oaLayoutTails();
      },
      onCompleted: function(p){
        var cites = (p && (p.citations || (p.data && p.data.citations))) || [];
        cites.slice(0, 3).forEach(function(c){
          var s = document.createElement('span');
          s.className = 'cite';
          s.textContent = '来源：' + (c.title || c.doc || c.source || '知识库');
          bubble.appendChild(s);
        });
      },
      onError: function(err){
        tx.textContent = '生成失败：' + (err.message || '未知错误');
        tx.style.color = 'var(--red)';
      }
    });
    if(!text) tx.textContent = '（本次未返回内容）';
    else{
      bubble.classList.add('ans');
      tx.innerHTML = (typeof formatAnswer === 'function' ? formatAnswer(text) : txt(text));
    }
  }catch(e){
    tx.textContent = '请求失败：' + (e.message || '请检查网络或后端服务');
    tx.style.color = 'var(--red)';
  }finally{
    S.busy = false;
    if(stop) stop.style.display = 'none';
    oaScrollDock();
    oaLayoutTails();
    refreshShared();
  }
}

async function oaStop(){
  if(!S.busy) return;
  var rid = (state.runId != null) ? state.runId : null;
  // 停止生成：经典链路把 runId 存在 state.runId 上，这里沿用同一字段
  if(rid){ try{ await API.cancel(rid); toast('已请求停止生成'); }catch(e){ toast('停止失败：'+(e.message||'')); } }
}

/* 新对话：清空对话坞与会话绑定（不动经典形态的 state.conversationId） */
function oaNewChat(){
  if(S.busy){ toast('正在生成，请先停止'); return; }
  S.convId = null; S.worker = null; S.expert = null;
  var list = dockEl(); if(list) list.innerHTML = '';
  oaSetChatting(false);
  S.view = 'home'; oaGo('home');
  var i = $o('oaInput'); if(i) i.focus();
  toast('已开启新对话，点数字人可选择数字员工或专家');
}

/* 新工作任务：workerIntent 识别类型 → 命中在册数字员工则直接对话，否则回到选择卡 */
async function oaNewTask(){
  askDialog({
    title:'新工作任务', mode:'input',
    message:'用一句话描述要办的事，系统会识别应交给哪类数字员工',
    placeholder:'例如：帮我起草一份周报', required:true,
    onOk: async function(v){
      var text = String(v || '').trim();
      var intent = null;
      try{ intent = await API.workerIntent(text); }catch(e){ intent = null; }
      var code = intent && (intent.role || intent.workerType);
      var hit = code ? arr(state.workers).filter(function(w){
        return String(w.workerType || '').toUpperCase() === String(code).toUpperCase() && w.on !== false;
      })[0] : null;
      if(hit){
        toast('已识别为「' + (intent.roleName || code) + '」，交给 ' + (hit.name || '数字员工'));
        oaPickWorker(hit);
        var i = $o('oaInput'); if(i){ i.value = text; oaSend(); }
      }else{
        toast(intent && intent.roleName
          ? ('识别为「' + intent.roleName + '」，当前无匹配的在册数字员工，请手动选择')
          : '未能识别类型，请手动选择数字员工或专家');
        oaOpenSheet();
      }
    }
  });
}

/* ------------------------------------------------------------- 10. 抽屉 / 弹层 */
function oaOpenDrawer(){
  var r = $o('oaRoot'); if(!r) return;
  r.classList.add('drawer-open');
  renderDrawer();
}
function oaCloseDrawer(){ var r = $o('oaRoot'); if(r) r.classList.remove('drawer-open'); }
function oaOpenSheet(){ var r = $o('oaRoot'); if(r) r.classList.add('sheet-open'); fillSheet(); }
function oaCloseSheet(){ var r = $o('oaRoot'); if(r) r.classList.remove('sheet-open'); }

function fillSheet(){
  var wn = $o('oaSheetWN'), en = $o('oaSheetEN');
  if(wn) wn.textContent = arr(state.workers).length + ' 位可用';
  if(en) en.textContent = arr(state.experts).length + ' 位可用';
  var tn = $o('odTimersN'), sn = $o('odSkillsN');
  if(tn) tn.textContent = String(arr(state.workers).filter(function(w){ return has(w.scheduleTime); }).length);
  if(sn) sn.textContent = String(arr(state.skills).length);
}

function renderDrawer(){
  var box = $o('oaDrawerRecent'); if(!box) return;
  var cs = arr(state.conversations);
  if(!cs.length){ box.innerHTML = empty('暂无最近会话'); return; }
  box.innerHTML = cs.slice(0, 6).map(function(c){
    return '<div class="recent-item" data-conv="'+txt(c.id)+'">'+
      '<div class="ri-ico">'+ic('chat',17)+'</div>'+
      '<div class="ri-txt"><span class="ri-t">'+txt(c.title || ('会话 #' + c.id))+'</span>'+
      '<span class="ri-s">'+txt(dt(c.lastMsgAt || c.createdAt))+'</span></div></div>';
  }).join('');
  box.querySelectorAll('[data-conv]').forEach(function(r){
    r.onclick = function(){ oaCloseDrawer(); oaResumeConversation(Number(r.dataset.conv)); };
  });
}

/* 续聊：载入历史消息到对话坞（原地，不跳经典会话页） */
async function oaResumeConversation(id){
  try{
    var msgs = arr(await API.listMessages(id));
    S.convId = id;
    var list = dockEl(); if(list) list.innerHTML = '';
    if(!msgs.length) oaPushBub('ai', '这条会话还没有消息，直接输入即可继续。');
    msgs.forEach(function(m){
      var isUser = m.role === 'user';
      oaPushBub(isUser ? 'user' : 'ai', isUser ? txt(m.content || m.text || '') : (txt(m.content || m.text || '')), {ans:!isUser});
    });
    S.view = 'home'; oaGo('home');
    if(list && !list.querySelector('.oa-who')){
      var d = document.createElement('div');
      d.className = 'oa-who';
      d.style.cssText = 'align-self:center;font-size:11px;color:var(--text-3);margin:2px 0 4px';
      d.textContent = '历史会话 #' + id + '（继续输入可持续对话）';
      list.insertBefore(d, list.firstChild);
    }
  }catch(e){
    toast('载入会话失败：' + (e.message || '未知错误'));
  }
}

/* -------------------------------------------------------------- 11. 数据刷新 */
/* 只补经典形态没加载的部分；其余一律读既有 state，避免第二份真值 */
async function loadOaExtras(){
  var r = await Promise.all([
    loadOrgAll().catch(function(){ return null; }),
    API.leaveMine().catch(function(){ return []; }),
    (!arr(state.conversations).length ? API.listConversations().catch(function(){ return []; }) : Promise.resolve(state.conversations))
  ]);
  S.leave = arr(r[1]);
  if(arr(r[2]).length) state.conversations = arr(r[2]);
}
/* 审批决策后刷新：经典 commitApprovalDecision 已刷新 state，这里只需重绘 */
function oaRefreshAfterDecide(){
  if(S.mode !== 'oa') return;
  // 决策完成后回到审批面板（经典函数会把页面切到 page-todo；OA 形态不受其影响）
  S.view = 'collab'; S.rail = 'approvals';
  oaRender();
  loadOaExtras().then(function(){ if(S.mode === 'oa') oaRender(); });
}
/* 走一遍既有的 live 加载，保证 OA 与经典读的是同一份 state */
async function refreshShared(){
  try{ await loadLiveData(); }catch(e){}
  try{ await loadOaExtras(); }catch(e){}
  if(S.mode === 'oa') oaRender();
}

/* ---------------------------------------------------------------- 12. 事件绑定 */
function bind(){
  ROBOT = $o('oaRobot');
  if(ROBOT) ROBOT.onclick = oaOpenSheet;

  var tabs = $o('oaTabs');
  if(tabs) tabs.querySelectorAll('.tab').forEach(function(t){
    t.onclick = function(){ oaGo(t.dataset.view); };
  });
  var rail = $o('oaRail');
  if(rail) rail.querySelectorAll('.rail-item').forEach(function(r){
    r.onclick = function(){ S.rail = r.dataset.panel; oaRender(); };
  });

  var send = $o('oaSendBtn'); if(send) send.onclick = oaSend;
  var stop = $o('oaStop'); if(stop) stop.onclick = oaStop;
  var input = $o('oaInput');
  if(input) input.addEventListener('keydown', function(e){
    if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); oaSend(); }
  });
  var dockList = dockEl();
  if(dockList) dockList.addEventListener('scroll', function(){ oaLayoutTails(); });
  /* 气泡的入场动画 bub-in 会在「首页从 display:none 恢复显示」时整体重放（浏览器行为）。
     重放期间 getBoundingClientRect 量到的是 translateY(8px) 的中间帧，据此定格的三角
     会偏约 1.2°（实测）。动画一结束就补量一次 —— 延时不来自这里，就不该在这里猜一个数。 */
  if(dockList) dockList.addEventListener('animationend', function(e){
    if(e.target && e.target.classList && e.target.classList.contains('bub')) oaLayoutTails();
  });

  var ov = $o('oaOverlay'); if(ov) ov.onclick = oaCloseDrawer;
  var mask = $o('oaSheetMask'); if(mask) mask.onclick = oaCloseSheet;
  var cancel = $o('oaSheetCancel'); if(cancel) cancel.onclick = oaCloseSheet;
  var nt = $o('oaNewTask');
  if(nt) nt.onclick = function(){ oaCloseSheet(); oaNewTask(); };

  document.querySelectorAll('#oaSheet .sheet-opt').forEach(function(o){
    o.onclick = function(){ oaCloseSheet(); oaGo(o.dataset.target); };
  });
  var odNew = $o('odNewTask');
  if(odNew) odNew.onclick = function(){ oaCloseDrawer(); oaNewTask(); };
  var odChat = $o('odNewChat');
  if(odChat) odChat.onclick = function(){ oaCloseDrawer(); oaNewChat(); };
  var odT = $o('odTimers');
  if(odT) odT.onclick = function(){ oaCloseDrawer(); oaGo('timers'); };
  var odS = $o('odSkills');
  if(odS) odS.onclick = function(){ oaCloseDrawer(); oaGo('skills'); };
  var odL = $o('odLogout');
  if(odL) odL.onclick = function(){ oaCloseDrawer(); doLogout(); resetMode(); };

  /* 布局切换按钮：两个形态各一个，类名统一，新增第三个也不会漏绑 */
  document.querySelectorAll('.js-layout-switch').forEach(function(b){
    b.onclick = toggleMode;
  });

  /* 账户内页的静态控件只绑一次（renderOa* 只重画数据区，不碰用户正在输入的内容） */
  var billExp = $o('oaBillExport');
  if(billExp) billExp.onclick = function(){
    if(typeof exportBill === 'function') exportBill();
  };
  var fbTxt = $o('oaFbContent');
  if(fbTxt) fbTxt.addEventListener('input', oaFbCount);
  var fbSub = $o('oaFbSubmit');
  if(fbSub) fbSub.onclick = oaSubmitFeedback;

  var kbQ = $o('oaKbQ');
  if(kbQ) kbQ.addEventListener('keydown', function(e){
    if(e.key !== 'Enter') return;
    var q = String(kbQ.value || '').trim();
    if(!q) return;
    API.kbSearch(q).then(function(res){
      var hits = arr(res && (res.items || res.hits) ? (res.items || res.hits) : res);
      var card = $o('oaKbList');
      if(!card) return;
      card.innerHTML = hits.length
        ? '<div class="muted" style="margin-bottom:8px">检索「'+txt(q)+'」命中 '+hits.length+' 条</div>' +
          hits.slice(0, 20).map(function(h){
            return '<div class="lrow">'+ic('doc')+'<div class="txt"><div class="t1 truncate">'+
              txt(h.title || h.name || h.doc || '文档片段')+'</div><div class="t2">'+
              txt(String(h.snippet || h.content || '').slice(0, 60))+'</div></div></div>';
          }).join('')
        : empty('未检索到「'+q+'」相关内容');
    }).catch(function(e2){ toast('检索失败：' + (e2.message || '')); });
  });

  var up = $o('oaKbUpload');
  var file = $o('oaKbFile');
  if(up && file){
    up.onclick = function(){ file.click(); };
    file.onchange = async function(){
      var f = file.files && file.files[0]; if(!f) return;
      toast('上传中：' + f.name);
      try{
        await API.kbUploadFile(f, 'PERSONAL');
        toast('已上传，服务端解析中');
        state.kbDocs = arr(await API.kbDocs());
        renderKb();
      }catch(e){ toast('上传失败：' + (e.message || '未知错误')); }
      file.value = '';
    };
  }

  var orgQ = $o('oaOrgQ');
  if(orgQ) orgQ.addEventListener('keydown', function(e){
    if(e.key !== 'Enter') return;
    S.orgQ = String(orgQ.value || '').trim();
    loadOrgMembers().then(renderOrg).catch(function(e2){ toast('查询失败：' + (e2.message || '')); });
  });

  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape'){ oaCloseDrawer(); oaCloseSheet(); }
  });
}

/* ------------------------------------------------------------------ 13. 引导 */
function oaBoot(){
  applyMode();
  if(S.mode !== 'oa') return;
  loadOaExtras().then(function(){ fillSheet(); oaRender(); }).catch(function(){});
  fillSheet();
}
window.oaBoot = oaBoot;
window.oaSetMode = setMode;
window.oaLayoutTails = oaLayoutTails;
window.oaState = S;

/* 不修改既有脚本一行：靠观察 body.auth 联动登录 / 登出 */
new MutationObserver(function(){
  var was = phoneEl() && phoneEl().classList.contains('oa-mode');
  applyMode();
  var now = phoneEl() && phoneEl().classList.contains('oa-mode');
  if(now && !was) loadOaExtras().then(function(){ oaRender(); }).catch(function(){});
  if(!authed()){ S.convId = null; S.worker = null; S.expert = null; }
}).observe(document.body, {attributes:true, attributeFilter:['class']});

/* 经典形态刷新后补一次 OA 侧重绘。
   refreshPermissions / renderFeedback 是经典形态里「刷数据 → 重画」的唯一入口，
   这里只做装饰：不复制它们的分支，也不改它们的行为，只在返回后补画 OA 的对应视图。
   （与上面的 wrapDecide 同一形态。） */
(function wrapOaDataRefresh(){
  function wrap(name, view){
    var orig = window[name];
    if(typeof orig !== 'function') return;
    window[name] = function(){
      var r = orig.apply(this, arguments);
      var repaint = function(){ if(S.mode === 'oa' && S.view === view) oaRender(); };
      if(r && typeof r.then === 'function'){ r.then(repaint, function(){}); } else { repaint(); }
      return r;
    };
  }
  wrap('refreshPermissions', 'perm');
  wrap('renderFeedback', 'feedback');
})();
/* 审批决策完成后补一次 OA 侧刷新。
   commitApprovalDecision 是「多级 / 单级」分流的唯一判定点（经典脚本内），
   这里只做装饰：不复制它的分支，只在它返回后补 OA 自己的重绘。 */
(function wrapDecide(){
  var orig = window.commitApprovalDecision;
  if(typeof orig !== 'function') return;
  window.commitApprovalDecision = async function(){
    var r = await orig.apply(this, arguments);
    try{ oaRefreshAfterDecide(); }catch(e){}
    return r;
  };
})();

try{
  var saved = localStorage.getItem(LS_MODE);
  S.mode = (saved === 'classic') ? 'classic' : MODE_DEFAULT;
}catch(e){ S.mode = MODE_DEFAULT; }

bind();
applyMode();
})();
