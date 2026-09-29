// Lightweight i18n for the AutoTeam Web UI (no heavy dependency).
// Two built-in locales (zh / en), switchable from the header.

import { computed, ref } from 'vue'

export type Locale = 'zh' | 'en'

const STORAGE_KEY = 'autoteam_locale'

const locale = ref<Locale>(
  localStorage.getItem(STORAGE_KEY) === 'zh' || localStorage.getItem(STORAGE_KEY) === 'en'
    ? (localStorage.getItem(STORAGE_KEY) as Locale)
    : 'zh',
)

const messages: Record<Locale, Record<string, string>> = {
  zh: {
    // app shell
    'app.name': 'AutoTeam',
    'app.tagline': 'Dynamic multi-agent execution',
    'app.version': 'v0.5.0',
    'app.mode_label': '运行模式',
    'nav.workspace': '工作台',
    'nav.runs': '运行',
    'nav.overview': '总览',
    'nav.team': '团队',
    'nav.artifacts': '交付物',
    'nav.result': '结果',
    'nav.lang': 'EN',
    'topbar.idle': '尚未选择任务',

    // status badge
    'status.pending': 'PENDING',
    'status.ready': 'READY',
    'status.running': 'RUNNING',
    'status.success': 'SUCCESS',
    'status.failed': 'FAILED',
    'status.retry': 'RETRY',
    'status.skipped': 'SKIPPED',

    // workspace
    'workspace.title': 'AutoTeam',
    'workspace.eyebrow': 'AUTOTEAM',
    'workspace.hero': 'Build a team for your task.',
    'workspace.subtitle':
      '动态多智能体执行 —— 描述一个任务，观看团队规划、协作并交付结果。',
    'workspace.input_label': '你希望你的 AI 团队做什么？',
    'workspace.input_placeholder': '描述你的任务…',
    'workspace.mode_label': '执行模式',
    'workspace.mode_offline': '离线',
    'workspace.mode_real': '真实 LLM',
    'workspace.run': '组建团队并运行',
    'workspace.starting': '启动中…',
    'workspace.examples': '示例任务',
    'workspace.ex_market': 'AI Agent 市场调研',
    'workspace.ex_market_value':
      '分析当前 AI Agent 市场的发展情况，重点关注产品方向、企业应用场景和技术趋势',
    'workspace.ex_ecommerce': '电商架构设计',
    'workspace.ex_ecommerce_value':
      '设计一个 FastAPI 电商后端系统，包含需求、架构、数据库与测试方案',
    'workspace.ex_saas': 'SaaS 市场进入',
    'workspace.ex_saas_value':
      '制定 SaaS 产品进入某行业的市场策略，包含客户洞察、竞品分析与财务评估',
    'workspace.recent': '最近运行（本后端会话）',
    'workspace.forming': '正在组建动态团队并开始执行…',

    // execution
    'exec.overview': '总览',
    'exec.running': '运行中…',
    'exec.run': 'RUN',
    'exec.agents_count': '智能体',
    'exec.layers_count': '层级',
    'exec.team_activity': 'TEAM ACTIVITY',
    'exec.no_activity': '等待该智能体事件…',
    'exec.provenance': 'PROVENANCE',
    'exec.mode_truth': '所有状态与数字均来自真实执行事件。',
    'exec.events': '事件',
    'exec.mode': '模式',
    'exec.team': '团队',
    'exec.team_forming': '团队组建中…',
    'exec.agent_details': '智能体详情',
    'exec.capabilities': '能力',
    'exec.tools': '工具',
    'exec.layer': '层级',
    'exec.feeds': '输出到',
    'exec.artifact': '交付物',
    'exec.artifact_src': '来源',
    'exec.artifact_ev': '证据',
    'exec.timeline': '执行',
    'exec.tool_calls': 'TOOL CALLS',
    'exec.no_tool_calls': '暂无工具调用',
    'exec.offline': '离线',
    'exec.web': '网页',
    'exec.evidence': 'Evidence',
    'exec.sources': 'Sources',
    'exec.waiting': '等待事件…',

    // activity labels (derived from real event types)
    'act.started': '开始',
    'act.tool_web': '搜索网页',
    'act.tool_offline': '离线工具',
    'act.artifact': '产出交付物',
    'act.output': '整理结果',
    'act.failed': '失败',
    'act.retrying': '重试中',
    'act.replanned': '已重规划',

    // team
    'team.dag': '依赖图谱',
    'team.waiting': '正在等待团队组建…',
    'team.agents': '智能体',
    'team.edges': '边',
    'team.layer': '层级',
    'team.layer_label': '执行层级',
    'team.artifact_flow': '交付物流向',
    'team.select_agent': '选择智能体以查看详情。',
    'team.formation': 'TEAM FORMATION',
    'team.canvas': 'TEAM CANVAS',
    'team.details': 'AGENT DETAILS',
    'team.capabilities': 'cap',
    'team.attempt': '尝试次数',
    'team.why': 'WHY THIS TEAM',

    // formation rail
    'tf.task_understanding': '理解任务',
    'tf.capability_discovery': '发现能力',
    'tf.role_allocation': '分配角色',
    'tf.agent_factory': '创建智能体',
    'tf.dag_validation': '校验 DAG',
    'tf.execution': '开始执行',

    // artifacts
    'art.none': '暂无交付物 —— 团队仍在工作中。',
    'art.flow': 'COLLABORATION FLOW',
    'art.expand': '展开',
    'art.collapse': '收起',
    'art.upstream': '上游',
    'art.key_data': '关键数据',
    'art.sources': '来源',
    'art.evidence': '证据',
    'art.offline': '(离线)',
    'art.consumed_by': '消费方',
    'art.consumed': '被消费于',
    'art.artifact_label': 'ARTIFACT',
    'art.content': '内容',
    'art.mode_real': '执行模式：Real · 来源真实',
    'art.mode_offline': '执行模式：Offline · 来源为 offline_mock',

    // result
    'result.not_ready': '最终交付物尚未就绪 —— 团队仍在工作中。',
    'result.deliverable': 'FINAL DELIVERABLE',
    'result.contents': 'CONTENTS',
    'result.assembled': '由真实智能体交付物汇总',
    'result.sources': '来源',
    'result.evidence': '证据',
    'result.sections': '章节',
    'result.copy': '复制',
    'result.copied': '已复制 ✓',
    'result.save': '保存 .md',
    'result.no_sources': '未记录来源。',
    'result.no_evidence': '未记录证据。',
    'result.offline_source': '(离线来源 —— 无 URL)',
  },
  en: {
    // app shell
    'app.name': 'AutoTeam',
    'app.tagline': 'Dynamic multi-agent execution',
    'app.version': 'v0.5.0',
    'app.mode_label': 'Execution mode',
    'nav.workspace': 'Workspace',
    'nav.runs': 'Runs',
    'nav.overview': 'Overview',
    'nav.team': 'Team',
    'nav.artifacts': 'Artifacts',
    'nav.result': 'Result',
    'nav.lang': '中文',
    'topbar.idle': 'No task selected',

    // status badge
    'status.pending': 'PENDING',
    'status.ready': 'READY',
    'status.running': 'RUNNING',
    'status.success': 'SUCCESS',
    'status.failed': 'FAILED',
    'status.retry': 'RETRY',
    'status.skipped': 'SKIPPED',

    // workspace
    'workspace.title': 'AutoTeam',
    'workspace.eyebrow': 'AUTOTEAM',
    'workspace.hero': 'Build a team for your task.',
    'workspace.subtitle':
      'Dynamic multi-agent execution — describe a task and watch a team plan, collaborate and deliver.',
    'workspace.input_label': 'What do you want your AI team to do?',
    'workspace.input_placeholder': 'Describe your task…',
    'workspace.mode_label': 'Execution mode',
    'workspace.mode_offline': 'Offline',
    'workspace.mode_real': 'Real LLM',
    'workspace.run': 'Build Team & Run',
    'workspace.starting': 'Starting…',
    'workspace.examples': 'Example tasks',
    'workspace.ex_market': 'AI Agent Market Research',
    'workspace.ex_market_value':
      'Analyze the current AI Agent market: product direction, enterprise use cases and recent technical trends',
    'workspace.ex_ecommerce': 'E-commerce Architecture',
    'workspace.ex_ecommerce_value':
      'Design a FastAPI e-commerce backend: requirements, architecture, database and test plan',
    'workspace.ex_saas': 'SaaS Market Entry',
    'workspace.ex_saas_value':
      'Draft a SaaS go-to-market strategy: customer insight, competitor landscape and financial assessment',
    'workspace.recent': 'Recent runs (this backend session)',
    'workspace.forming': 'Forming the dynamic team and starting execution…',

    // execution
    'exec.overview': 'Overview',
    'exec.running': 'Running…',
    'exec.run': 'RUN',
    'exec.agents_count': 'agents',
    'exec.layers_count': 'layers',
    'exec.team_activity': 'TEAM ACTIVITY',
    'exec.no_activity': 'No events for this agent yet…',
    'exec.provenance': 'PROVENANCE',
    'exec.mode_truth': 'Every status and number comes from real execution events.',
    'exec.events': 'events',
    'exec.mode': 'mode',
    'exec.team': 'Team',
    'exec.team_forming': 'Team is being formed…',
    'exec.agent_details': 'Agent details',
    'exec.capabilities': 'Capabilities',
    'exec.tools': 'Tools',
    'exec.layer': 'Layer',
    'exec.feeds': 'Feeds',
    'exec.artifact': 'Artifact',
    'exec.artifact_src': 'Sources',
    'exec.artifact_ev': 'Evidence',
    'exec.timeline': 'Execution',
    'exec.tool_calls': 'TOOL CALLS',
    'exec.no_tool_calls': 'No tool calls yet',
    'exec.offline': 'offline',
    'exec.web': 'web',
    'exec.evidence': 'Evidence',
    'exec.sources': 'Sources',
    'exec.waiting': 'Waiting for events…',

    // activity labels (derived from real event types)
    'act.started': 'started',
    'act.tool_web': 'web search',
    'act.tool_offline': 'offline tool',
    'act.artifact': 'artifact',
    'act.output': 'output',
    'act.failed': 'failed',
    'act.retrying': 'retrying',
    'act.replanned': 'replanned',

    // team
    'team.dag': 'Dependency graph',
    'team.waiting': 'Waiting for team formation…',
    'team.agents': 'agents',
    'team.edges': 'edges',
    'team.layer': 'Execution layer',
    'team.layer_label': 'Execution layer',
    'team.artifact_flow': 'Artifact flow',
    'team.select_agent': 'Select an agent to inspect it.',
    'team.formation': 'TEAM FORMATION',
    'team.canvas': 'TEAM CANVAS',
    'team.details': 'AGENT DETAILS',
    'team.capabilities': 'cap',
    'team.attempt': 'Attempt',
    'team.why': 'WHY THIS TEAM',

    // formation rail
    'tf.task_understanding': 'Task understanding',
    'tf.capability_discovery': 'Capability discovery',
    'tf.role_allocation': 'Role allocation',
    'tf.agent_factory': 'Agent factory',
    'tf.dag_validation': 'DAG validation',
    'tf.execution': 'Execution',

    // artifacts
    'art.none': 'No artifacts yet — the team is still working.',
    'art.flow': 'COLLABORATION FLOW',
    'art.expand': 'Expand',
    'art.collapse': 'Collapse',
    'art.upstream': 'Upstream',
    'art.key_data': 'Key data',
    'art.sources': 'Sources',
    'art.evidence': 'Evidence',
    'art.offline': '(offline)',
    'art.consumed_by': 'consumed by',
    'art.consumed': 'Consumed by',
    'art.artifact_label': 'ARTIFACT',
    'art.content': 'Content',
    'art.mode_real': 'Execution mode: Real · live sources',
    'art.mode_offline': 'Execution mode: Offline · offline_mock sources',

    // result
    'result.not_ready': 'The final deliverable is not ready yet — the team is still working.',
    'result.deliverable': 'FINAL DELIVERABLE',
    'result.contents': 'CONTENTS',
    'result.assembled': 'Assembled from real agent artifacts',
    'result.sources': 'Sources',
    'result.evidence': 'Evidence',
    'result.sections': 'Sections',
    'result.copy': 'Copy',
    'result.copied': 'Copied ✓',
    'result.save': 'Save .md',
    'result.no_sources': 'No sources recorded.',
    'result.no_evidence': 'No evidence recorded.',
    'result.offline_source': '(offline source — no URL)',
  },
}

export function useI18n() {
  const t = (key: string): string => messages[locale.value][key] ?? key
  const isZh = computed(() => locale.value === 'zh')

  function setLocale(next: Locale) {
    locale.value = next
    localStorage.setItem(STORAGE_KEY, next)
    document.documentElement.lang = next
  }

  function toggleLocale() {
    setLocale(locale.value === 'zh' ? 'en' : 'zh')
  }

  return { t, locale, isZh, setLocale, toggleLocale }
}