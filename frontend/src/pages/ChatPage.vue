<template>
  <div class="chat-wrap">
    <!-- 会话列表 -->
    <a-card class="session-panel" :bordered="false">
      <a-button type="primary" block style="margin-bottom: 8px" @click="newSession">
        <template #icon><PlusOutlined /></template>
        新对话
      </a-button>
      <div class="session-list chat-scroll">
        <a-empty v-if="!sessions.length" description="暂无会话" :image="simpleImage" />
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: sessionId === s.id }"
          @click="openSession(s.id)"
        >
          <a-tooltip :title="s.title">
            <span class="session-title">{{ s.title }}</span>
          </a-tooltip>
          <a-button type="text" size="small" @click.stop="exportSession(s)">
            <ExportOutlined />
          </a-button>
          <a-button type="text" size="small" @click.stop="renameSession(s)">
            <EditOutlined />
          </a-button>
          <a-button type="text" size="small" danger @click.stop="deleteSession(s.id)">
            <DeleteOutlined />
          </a-button>
        </div>
      </div>
    </a-card>

    <!-- 对话区 -->
    <a-card class="chat-panel" :bordered="false">
      <template #title>
        <span class="chat-title"><RobotOutlined style="color: #1668dc" /> 智能问答（RAG）</span>
        <a-select
          v-model:value="kbIds"
          style="width: 260px; margin-left: 16px"
          size="small"
          mode="multiple"
          placeholder="选择知识库（可多选联合检索）"
          :options="kbOptions"
          :max-tag-count="2"
        />
      </template>

      <div ref="scrollRef" class="msg-list chat-scroll">
        <!-- 空态：欢迎卡片 + 快捷问题，避免大片空白 -->
        <div v-if="!msgs.length" class="welcome">
          <div class="welcome-card">
            <RobotOutlined class="welcome-icon" />
            <h3>你好，我是 {{ kb?.name || '知识库' }} 智能助手</h3>
            <p>基于知识库文档回答你的问题，回答将标注引用来源。试试这些示例问题：</p>
            <div class="welcome-questions">
              <a-tag
                v-for="q in welcomeQuestions"
                :key="q"
                class="welcome-q"
                @click="quickAsk(q)"
              >
                {{ q }}
              </a-tag>
            </div>
          </div>
        </div>
        <div v-for="(m, i) in msgs" :key="i" class="msg-row">
          <div class="msg-avatar" :class="m.role === 'user' ? 'user' : 'assistant'">
            <UserOutlined v-if="m.role === 'user'" />
            <RobotOutlined v-else />
          </div>
          <div class="msg-body">
            <div class="message-bubble" :class="m.role">
              <div v-if="m.role === 'assistant'" v-html="renderMd(m.content)" class="md-body" />
              <template v-else>{{ m.content }}</template>
              <span v-if="m.streaming" class="typing-dots"><i class="typing-dot" /><i class="typing-dot" /><i class="typing-dot" /></span>
            </div>
            <div v-if="m.role === 'assistant' && m.citations?.length" class="cite-row">
              <a-popover v-for="(c, ci) in m.citations" :key="ci" trigger="click" placement="bottom">
                <template #title>引用 [{{ c.ref_index ?? ci + 1 }}]</template>
                <template #content>
                  <div class="citation-card">{{ c.snippet }}</div>
                  <div class="cite-meta">
                    {{ c.doc_name }}<template v-if="c.page"> · 第 {{ c.page }} 页</template> · 相关度 {{ c.score.toFixed(2) }}
                  </div>
                  <div style="margin-top: 6px">
                    <a-button size="small" type="link" @click="downloadDoc(c)">
                      <DownloadOutlined /> 下载原文
                    </a-button>
                  </div>
                </template>
                <a-tag class="citation-link" style="cursor: pointer">
                  <FileTextOutlined /> [{{ c.ref_index ?? ci + 1 }}] {{ c.doc_name }}<template v-if="c.page"> P{{ c.page }}</template>
                </a-tag>
              </a-popover>
            </div>
            <div v-if="m.role === 'assistant'" class="msg-footer">
              <span v-if="m.model" class="cite-meta">模型：{{ m.model }}</span>
              <!-- 回答反馈（赞/踩） -->
              <a-space v-if="!m.streaming && m.id" size="small" class="feedback-row">
                <a-tooltip title="回答有帮助">
                  <a-button
                    type="text"
                    size="small"
                    :class="{ 'feedback-active': m.feedback === 'up' }"
                    @click="giveFeedback(m, 'up')"
                  >
                    <LikeOutlined :style="m.feedback === 'up' ? { color: '#52c41a' } : {}" />
                  </a-button>
                </a-tooltip>
                <a-tooltip title="回答有问题">
                  <a-button
                    type="text"
                    size="small"
                    :class="{ 'feedback-active': m.feedback === 'down' }"
                    @click="giveFeedback(m, 'down')"
                  >
                    <DislikeOutlined :style="m.feedback === 'down' ? { color: '#ff4d4f' } : {}" />
                  </a-button>
                </a-tooltip>
                <a-tooltip title="复制回答">
                  <a-button type="text" size="small" @click="copyAnswer(m)">
                    <CopyOutlined />
                  </a-button>
                </a-tooltip>
              </a-space>
            </div>
            <!-- 追问建议 -->
            <div v-if="m.role === 'assistant' && m.suggestions?.length" class="suggest-row">
              <a-tag
                v-for="q in m.suggestions"
                :key="q"
                class="suggest-q"
                @click="quickAsk(q)"
              >
                <BulbOutlined /> {{ q }}
              </a-tag>
            </div>
          </div>
        </div>
      </div>

      <div class="input-row">
        <a-textarea
          v-model:value="input"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          :auto-size="{ minRows: 1, maxRows: 5 }"
          @keydown="onKeydown"
        />
        <a-button type="primary" :loading="sending" @click="send">
          <template #icon><SendOutlined /></template>
          发送
        </a-button>
      </div>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  BulbOutlined,
  CopyOutlined,
  DeleteOutlined,
  DislikeOutlined,
  DownloadOutlined,
  EditOutlined,
  ExportOutlined,
  FileTextOutlined,
  LikeOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'
import { Empty } from 'ant-design-vue'
import { marked } from 'marked'
import { api, errMsg, getToken } from '../api'
import type { ChatMessageItem, ChatSessionItem, Citation, KnowledgeBase, Msg, SSEEvent } from '../types'

const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE

const kbs = ref<KnowledgeBase[]>([])
const kbIds = ref<number[]>([])
const kb = ref<KnowledgeBase | null>(null)
const sessions = ref<ChatSessionItem[]>([])
const sessionId = ref<number | null>(null)
const msgs = ref<Msg[]>([])
const input = ref('')
const sending = ref(false)
const scrollRef = ref<HTMLElement>()
let abortCtrl: AbortController | null = null

const welcomeQuestions = computed(() => {
  const qs = kb.value?.welcome_questions
  if (qs && qs.length) return qs.slice(0, 6)
  return ['这个知识库包含哪些内容？', '员工年假怎么计算？', '住宿报销标准是多少？']
})

const kbOptions = computed(() => kbs.value.map((k) => ({ value: k.id, label: k.name })))

function renderMd(text: string): string {
  try {
    // 预处理：压缩连续空行(>2)与行尾空白，避免 AI 输出中的多余空行撑出大段空白
    const cleaned = (text || '')
      .replace(/\r\n/g, '\n')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
    return marked.parse(cleaned, { async: false, gfm: true, breaks: false }) as string
  } catch {
    return text || ''
  }
}

async function loadKbs() {
  try {
    const { data } = await api.get<KnowledgeBase[]>('/kbs')
    kbs.value = data
    if (data.length && kbIds.value.length === 0) kbIds.value = [data[0].id]
    syncWelcomeKb()
  } catch (e) {
    message.error(errMsg(e))
  }
}

function syncWelcomeKb() {
  kb.value = kbs.value.find((k) => k.id === (kbIds.value[0] ?? null)) || null
}

function quickAsk(q: string) {
  input.value = q
  send()
}

// 切换知识库时同步欢迎卡片名称
watch(kbIds, syncWelcomeKb)

async function loadSessions() {
  try {
    const { data } = await api.get<ChatSessionItem[]>('/chat/sessions')
    sessions.value = data
  } catch {
    /* ignore */
  }
}

onMounted(() => {
  loadKbs()
  loadSessions()
})
onBeforeUnmount(() => abortCtrl?.abort())

function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function openSession(id: number) {
  sessionId.value = id
  msgs.value = []
  try {
    const { data } = await api.get<ChatMessageItem[]>(`/chat/sessions/${id}/messages`)
    msgs.value = data.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      citations: m.citations,
      model: m.model,
      suggestions: (m as ChatMessageItem & { suggested?: string[] }).suggested || [],
    }))
    scrollToBottom()
  } catch (e) {
    message.error(errMsg(e))
  }
}

function newSession() {
  abortCtrl?.abort()
  sessionId.value = null
  msgs.value = []
}

async function deleteSession(id: number) {
  try {
    await api.delete(`/chat/sessions/${id}`)
    if (sessionId.value === id) newSession()
    loadSessions()
  } catch (e) {
    message.error(errMsg(e))
  }
}

function patchLast(patch: Partial<Msg>) {
  const last = msgs.value[msgs.value.length - 1]
  if (last) Object.assign(last, patch)
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  if (!kbIds.value.length) {
    message.warning('请先选择知识库')
    return
  }
  input.value = ''
  msgs.value.push({ role: 'user', content: text })
  msgs.value.push({ role: 'assistant', content: '', streaming: true })
  sending.value = true
  scrollToBottom()

  const ctrl = new AbortController()
  abortCtrl = ctrl
  let full = ''
  let citations: Citation[] | null = null
  let model = ''
  let doneSession: number | null = null
  let doneMsgId: number | null = null

  try {
    const resp = await fetch('/api/chat/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({
        kb_id: kbIds.value[0],
        kb_ids: kbIds.value.slice(1),
        message: text,
        session_id: sessionId.value,
        top_k: 8,
      }),
      signal: ctrl.signal,
    })
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n\n')
      buf = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        let ev: SSEEvent
        try {
          ev = JSON.parse(line.slice(6))
        } catch {
          continue
        }
        if (ev.type === 'meta') {
          citations = ev.citations ?? null
          model = ev.model || ''
        } else if (ev.type === 'delta') {
          full += ev.content || ''
          patchLast({ content: full, model: ev.model || model })
          scrollToBottom()
        } else if (ev.type === 'audit') {
          // 引用审计结果：替换为回答实际依据的片段
          citations = ev.citations ?? citations
          patchLast({ citations })
        } else if (ev.type === 'masked') {
          // 脱敏完成：替换为打码版本
          if (ev.content) {
            full = ev.content
            patchLast({ content: full })
          }
        } else if (ev.type === 'suggest') {
          patchLast({ suggestions: ev.questions || [] })
        } else if (ev.type === 'done') {
          doneSession = ev.session_id ?? null
          doneMsgId = ev.message_id ?? null
          patchLast({ streaming: false, citations, model, id: doneMsgId ?? undefined })
        } else if (ev.type === 'error') {
          patchLast({ streaming: false, error: true, content: `⚠️ ${ev.message || '生成失败'}` })
        }
      }
    }
    if (doneSession) {
      sessionId.value = doneSession
      loadSessions()
    }
  } catch (e) {
    if ((e as Error).name !== 'AbortError') {
      const last = msgs.value[msgs.value.length - 1]
      if (last) {
        last.streaming = false
        last.error = true
        last.content = last.content || `⚠️ 请求失败：${errMsg(e)}`
      }
    }
  } finally {
    sending.value = false
    loadSessions()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// ---------------- 回答反馈 / 复制 / 引用下载 / 会话重命名 ----------------
async function giveFeedback(m: Msg, rating: 'up' | 'down') {
  if (!m.id) return
  // 点击相同按钮取消反馈
  const next = m.feedback === rating ? null : rating
  try {
    await api.post(`/chat/messages/${m.id}/feedback`, { rating: next ?? 'up' })
    m.feedback = next
    message.success(next ? (next === 'up' ? '已标记为有帮助' : '已标记为需改进') : '已取消反馈')
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function copyAnswer(m: Msg) {
  try {
    await navigator.clipboard.writeText(m.content || '')
    message.success('已复制到剪贴板')
  } catch {
    message.error('复制失败')
  }
}

async function downloadDoc(c: Citation) {
  if (!c.kb_id || !c.doc_id) return
  try {
    const resp = await fetch(`/api/kbs/${c.kb_id}/documents/${c.doc_id}/download`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = c.doc_name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(`下载失败：${errMsg(e)}`)
  }
}

async function renameSession(s: ChatSessionItem) {
  // 简洁重命名：prompt 输入新标题
  const title = window.prompt('请输入新的会话标题：', s.title)
  if (!title || title.trim() === s.title) return
  try {
    await api.patch(`/chat/sessions/${s.id}`, { title: title.trim() })
    s.title = title.trim()
    message.success('已重命名')
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function exportSession(s: ChatSessionItem) {
  try {
    const resp = await fetch(`/api/chat/sessions/${s.id}/export?format=markdown`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `会话_${s.title.slice(0, 30)}.md`
    a.click()
    URL.revokeObjectURL(url)
    message.success('会话已导出（Markdown）')
  } catch (e) {
    message.error(`导出失败：${errMsg(e)}`)
  }
}
</script>

<style scoped>
/* 弹性填充：Content 为 flex 列布局时，flex:1 + min-height:0 精确占满剩余空间，
   overflow hidden 兜底：内部任何溢出都不得外泄触发页面/Content 滚动 */
.chat-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 16px;
  overflow: hidden;
}
.session-panel {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.session-panel :deep(.ant-card-body) {
  padding: 8px;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.session-list {
  overflow: auto;
  flex: 1;
  min-height: 0;
}
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.session-item:hover {
  background: #f5f7fa;
}
.session-item.active {
  background: #e6f4ff;
}
.session-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.chat-panel :deep(.ant-card-body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 12px;
  min-height: 0;
}
.chat-title {
  font-weight: 600;
}
.msg-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overflow-x: hidden;
  background: #fafbfc;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 16px;
}
/* 欢迎卡片：空态不再是空白 */
.welcome {
  display: flex;
  justify-content: center;
  padding-top: 6vh;
}
.welcome-card {
  text-align: center;
  max-width: 560px;
}
.welcome-icon {
  font-size: 52px;
  color: #1668dc;
}
.welcome-card h3 {
  margin: 12px 0 8px;
}
.welcome-card p {
  color: #8c8c8c;
  margin: 0 0 16px;
}
.welcome-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
.welcome-q {
  cursor: pointer;
  padding: 6px 14px;
  font-size: 13px;
  border-radius: 16px;
  transition: all 0.2s;
}
.welcome-q:hover {
  color: #1668dc;
  border-color: #1668dc;
}
.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.msg-avatar {
  width: 30px;
  height: 30px;
  border-radius: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.msg-avatar.user {
  background: #1668dc;
}
.msg-avatar.assistant {
  background: #52c41a;
}
.msg-body {
  flex: 1;
  min-width: 0;
}
/* 气泡占满可用宽度：回答内容不再缩成窄条、右侧不留大片空白 */
.message-bubble {
  background: #fff;
  border: 1px solid #f0f0f0;
  padding: 12px 16px;
  border-radius: 8px;
}
.message-bubble.user {
  background: #e6f4ff;
}
/* AI 输出 Markdown 紧凑排版：收紧段落/标题/列表间距，
   消除“### 小标题 + 空行 + 单行列表”结构下的大片垂直空白 */
.md-body {
  /* 关键：v-html 的 HTML 源码含大量换行符，若继承 pre-wrap 会被渲染成可见空行；
     normal 下间距完全由 CSS margin 控制 */
  white-space: normal;
  line-height: 1.6;
  font-size: 14px;
}
.md-body :deep(p) {
  margin: 0 0 4px;
}
.md-body :deep(p:last-child) {
  margin-bottom: 0;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  padding-left: 20px;
  margin: 2px 0 4px;
}
.md-body :deep(li) {
  margin: 0;
}
.md-body :deep(li > p) {
  margin: 0;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 8px 0 3px;
  font-size: 15px;
  line-height: 1.4;
}
.md-body :deep(pre) {
  margin: 6px 0;
  padding: 8px 12px;
  background: #f6f8fa;
  border-radius: 6px;
  overflow: auto;
}
.md-body :deep(code) {
  font-size: 12px;
}
.md-body :deep(blockquote) {
  margin: 6px 0;
  padding-left: 12px;
  border-left: 3px solid #d9d9d9;
  color: #666;
}
.md-body :deep(table) {
  margin: 6px 0;
  border-collapse: collapse;
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid #e8e8e8;
  padding: 5px 10px;
  font-size: 13px;
}
.md-body :deep(hr) {
  margin: 10px 0;
  border: none;
  border-top: 1px solid #f0f0f0;
}
.md-body :deep(strong) {
  font-weight: 600;
}
.cite-row {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.citation-card {
  border-left: 3px solid #1668dc;
  background: #f0f5ff;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 8px;
  max-width: 420px;
  max-height: 160px;
  overflow: auto;
}
.cite-meta {
  color: #999;
  font-size: 11px;
}
.msg-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}
.feedback-row {
  margin-left: 8px;
}
.feedback-row :deep(.ant-btn) {
  font-size: 12px;
  color: #bfbfbf;
}
.feedback-row :deep(.ant-btn:hover) {
  color: #1668dc;
}
.feedback-active :deep(.anticon) {
  color: inherit;
}
.suggest-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.suggest-q {
  cursor: pointer;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 14px;
  transition: all 0.2s;
}
.suggest-q:hover {
  color: #1668dc;
  border-color: #1668dc;
}
.input-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  /* 输入区固定贴底，不被消息区压缩 */
  flex-shrink: 0;
}
</style>