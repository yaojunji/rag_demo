<template>
  <div class="docs-page">
    <a-card :bordered="false">
      <div class="docs-head">
        <a-space>
          <a-button @click="$router.push('/kbs')"><ArrowLeftOutlined /> 返回</a-button>
          <h3 style="margin: 0">{{ kb?.name || '知识库' }}</h3>
        </a-space>
        <a-space>
          <a-button v-if="auth.isEditor" :loading="exporting" @click="exportKb">
            <DownloadOutlined /> 导出备份
          </a-button>
          <a-popover v-if="!auth.isEditor" trigger="hover">
            <template #content>当前账号为只读角色，无法上传文档。<br />请联系管理员提升权限。</template>
            <a-button type="primary" disabled><UploadOutlined /> 上传文档</a-button>
          </a-popover>
          <a-button v-else type="primary" :loading="uploadingCount > 0" @click="fileInput?.click()">
            <UploadOutlined /> 上传文档
          </a-button>
          <input
            ref="fileInput"
            type="file"
            multiple
            style="display: none"
            @change="onFilesSelected"
          />
          <input
            ref="replaceInput"
            type="file"
            style="display: none"
            @change="onReplaceSelected"
          />
        </a-space>
      </div>
      <a-descriptions v-if="kb" size="small" :column="4" style="margin-top: 12px">
        <a-descriptions-item label="描述">{{ kb.description || '—' }}</a-descriptions-item>
        <a-descriptions-item label="文档数">{{ kb.doc_count }}</a-descriptions-item>
        <a-descriptions-item label="分块数">{{ kb.chunk_count }}</a-descriptions-item>
        <a-descriptions-item label="向量模型">{{ kb.embed_model }}</a-descriptions-item>
      </a-descriptions>

      <!-- 上传队列 -->
      <div v-if="uploadQueue.length" class="upload-queue">
        <div v-for="item in uploadQueue" :key="item.key" class="upload-item">
          <div class="upload-info">
            <span class="upload-name">{{ item.name }}</span>
            <a-tag v-if="item.status === 'uploading'" color="processing">上传中 {{ item.percent }}%</a-tag>
            <a-tag v-else-if="item.status === 'done'" color="success">已提交索引</a-tag>
            <a-tag v-else-if="item.status === 'error'" color="error">失败</a-tag>
          </div>
          <a-progress v-if="item.status === 'uploading'" :percent="item.percent" size="small" style="width: 240px" />
          <div v-if="item.error" class="upload-error">{{ item.error }}</div>
        </div>
      </div>
    </a-card>

    <a-card :bordered="false" style="margin-top: 16px">
      <template #title>
        <a-tabs v-model:activeKey="listTab" size="small" style="margin-bottom: 0">
          <a-tab-pane key="docs" tab="文档列表">
            <template v-if="selectedIds.length" style="display: block">
              <a-space style="margin-bottom: 8px">
                <span style="font-size: 12px; color: #666">已选 {{ selectedIds.length }} 项</span>
                <a-button size="small" @click="batchOp('reindex')">批量重建</a-button>
                <a-popconfirm title="批量删除所选文档（进回收站）？" @confirm="batchOp('delete')">
                  <a-button size="small" danger>批量删除</a-button>
                </a-popconfirm>
                <a-button size="small" type="link" @click="selectedIds = []">取消选择</a-button>
              </a-space>
            </template>
            <a-table
              :data-source="docs"
              :columns="columns"
              :loading="loading"
              row-key="id"
              :row-selection="{ selectedRowKeys: selectedIds, onChange: (ks: number[]) => (selectedIds = ks) }"
              :pagination="{ pageSize: 10, showTotal: (t: number) => `共 ${t} 条` }"
            >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'filename'">
            <span style="font-weight: 600">{{ record.filename }}</span>
          </template>
          <template v-else-if="column.key === 'file_type'">
            <a-tag>{{ record.file_type }}</a-tag>
          </template>
          <template v-else-if="column.key === 'file_size'">
            {{ fmtSize(record.file_size) }}
          </template>
          <template v-else-if="column.key === 'status'">
            <a-space>
              <a-tag :color="statusMap[record.status].color">{{ statusMap[record.status].text }}</a-tag>
              <a-progress v-if="record.status === 'processing'" type="circle" :size="18" :percent="record.progress" />
            </a-space>
          </template>
          <template v-else-if="column.key === 'sensitive'">
            <template v-if="record.sensitive_flags">
              <a-tooltip>
                <template #title>{{ sensitiveText(record.sensitive_flags) }}</template>
                <a-tag color="warning"><SafetyCertificateOutlined /> 含敏感信息</a-tag>
              </a-tooltip>
            </template>
            <span v-else style="color: #bbb">—</span>
          </template>
          <template v-else-if="column.key === 'error'">
            <a-tooltip v-if="record.error" :title="record.error">
              <span style="color: #ff4d4f; font-size: 12px">{{ record.error }}</span>
            </a-tooltip>
            <span v-else>—</span>
          </template>
          <template v-else-if="column.key === 'chunk_count'">
            {{ record.chunk_count || 0 }}
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ fmtTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-button size="small" :disabled="record.status !== 'ready'" @click="openPreview(record)">预览</a-button>
              <a-button size="small" :disabled="record.status !== 'ready'" @click="openChunks(record)">分块</a-button>
              <a-button size="small" :disabled="record.status === 'processing'" @click="reindex(record)">
                <ReloadOutlined /> 重建
              </a-button>
              <a-tooltip title="上传新文件替换当前版本（保留记录与引用）">
                <a-button size="small" :disabled="record.status === 'processing'" @click="openReplace(record)">
                  <SyncOutlined /> 更新
                </a-button>
              </a-tooltip>
              <a-popconfirm title="删除该文档（进回收站，可恢复）？" @confirm="del(record)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
          </a-tab-pane>
          <a-tab-pane key="trash" tab="回收站">
            <a-table
              :data-source="trashDocs"
              :columns="trashColumns"
              row-key="id"
              :pagination="{ pageSize: 10, showTotal: (t: number) => `共 ${t} 条` }"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'deleted_at'">
                  {{ fmtTime(record.deleted_at) }}
                </template>
                <template v-else-if="column.key === 'action'">
                  <a-space>
                    <a-button size="small" type="primary" ghost @click="restore(record)">恢复</a-button>
                    <a-popconfirm title="彻底删除？不可恢复！" @confirm="purge(record)">
                      <a-button size="small" danger>彻底删除</a-button>
                    </a-popconfirm>
                  </a-space>
                </template>
              </template>
            </a-table>
          </a-tab-pane>
        </a-tabs>
      </template>
    </a-card>

    <a-drawer :open="!!chunkDoc" :title="chunkDoc ? `分块预览：${chunkDoc.filename}（${chunks.length} 块）` : ''" width="640" @close="chunkDoc = null">
      <div v-if="chunksLoading" style="color: #999">加载中…</div>
      <a-card v-for="c in chunks" :key="c.chunk_index" size="small" style="margin-bottom: 8px" :title="`片段 #${c.chunk_index + 1}${c.metadata.page ? ` · 第 ${c.metadata.page} 页` : ''}`">
        <div style="white-space: pre-wrap; font-size: 13px">{{ c.content }}</div>
      </a-card>
    </a-drawer>

    <!-- 文档预览 -->
    <a-drawer :open="previewOpen" :title="previewDoc ? previewDoc.filename : ''" width="70%" @close="previewOpen = false">
      <div v-if="previewLoading" style="color: #999">加载中…</div>
      <iframe
        v-else-if="previewUrl && previewDoc?.file_type === 'pdf'"
        :src="previewUrl"
        style="width: 100%; height: calc(100vh - 120px); border: none"
      />
      <pre v-else-if="previewText !== null" style="white-space: pre-wrap; font-size: 13px; line-height: 1.7">{{ previewText }}</pre>
      <div v-else-if="previewDoc" style="color: #999">该类型暂不支持在线预览，请下载后查看</div>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SyncOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import { fmtTime } from '../utils/time'
import { api, errMsg, getToken } from '../api'
import { useAuthStore } from '../stores/auth'
import type { ChunkItem, DocumentItem, KnowledgeBase } from '../types'

const route = useRoute()
const auth = useAuthStore()
const kbId = Number(route.params.kbId)
const kb = ref<KnowledgeBase | null>(null)
const docs = ref<DocumentItem[]>([])
const trashDocs = ref<DocumentItem[]>([])
const loading = ref(false)
const listTab = ref('docs')
const selectedIds = ref<number[]>([])
const chunkDoc = ref<DocumentItem | null>(null)
const chunks = ref<ChunkItem[]>([])
const chunksLoading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

interface UploadTask {
  key: number
  name: string
  status: 'uploading' | 'done' | 'error'
  percent: number
  error: string
}
const uploadQueue = ref<UploadTask[]>([])
let uploadKey = 0
const uploadingCount = computed(() => uploadQueue.value.filter((t) => t.status === 'uploading').length)

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待中' },
  processing: { color: 'processing', text: '索引中' },
  ready: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
}

const columns = [
  { title: '文件名', key: 'filename', ellipsis: true },
  { title: '类型', key: 'file_type', width: 80 },
  { title: '大小', key: 'file_size', width: 100 },
  { title: '状态', key: 'status', width: 180 },
  { title: '敏感信息', key: 'sensitive', width: 120 },
  { title: '错误信息', key: 'error', ellipsis: true },
  { title: '分块', key: 'chunk_count', width: 80 },
  { title: '上传时间', key: 'created_at', width: 150 },
  { title: '操作', key: 'action', width: 220 },
]

const trashColumns = [
  { title: '文件名', key: 'filename', ellipsis: true },
  { title: '类型', key: 'file_type', width: 80 },
  { title: '大小', key: 'file_size', width: 100 },
  { title: '删除时间', key: 'deleted_at', width: 150 },
  { title: '操作', key: 'action', width: 180 },
]

const SENSITIVE_NAMES: Record<string, string> = {
  id_card: '身份证号',
  phone: '手机号',
  bank_card: '银行卡号',
  email: '邮箱',
  ip: 'IP地址',
  api_key: 'API密钥',
}

function sensitiveText(flags: string): string {
  return flags
    .split(',')
    .filter(Boolean)
    .map((f) => SENSITIVE_NAMES[f.trim()] || f.trim())
    .join('、')
}

function fmtSize(n: number) {
  if (n > 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB'
  if (n > 1024) return (n / 1024).toFixed(1) + ' KB'
  return n + ' B'
}
// 时间显示统一走 utils/time（UTC→本地）

async function load() {
  try {
    const [kbR, docR] = await Promise.all([
      api.get<KnowledgeBase>(`/kbs/${kbId}`),
      api.get<DocumentItem[]>(`/kbs/${kbId}/documents`),
    ])
    kb.value = kbR.data
    docs.value = docR.data
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function loadTrash() {
  try {
    const { data } = await api.get<DocumentItem[]>(`/kbs/${kbId}/documents/trash`)
    trashDocs.value = data
  } catch {
    /* ignore */
  }
}

function startPoll() {
  stopPoll()
  timer = setInterval(load, 3000)
}
function stopPoll() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function watchBusy() {
  const busy = docs.value.some((d) => d.status === 'pending' || d.status === 'processing')
  if (busy && !timer) startPoll()
  else if (!busy) stopPoll()
}
async function loadAndWatch() {
  await load()
  watchBusy()
}

onMounted(async () => {
  loading.value = true
  await load()
  loading.value = false
  watchBusy()
  loadTrash()
})
onBeforeUnmount(stopPoll)

// ---------------- 原生文件上传（绕开组件库 Upload，保证可靠） ----------------
function onFilesSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = '' // 允许重复选择同一文件
  if (!files.length) return
  // ZIP 走批量导入
  if (files.length === 1 && files[0].name.toLowerCase().endsWith('.zip')) {
    uploadZip(files[0])
    return
  }
  const tasks: UploadTask[] = files.map((f) => ({
    key: ++uploadKey,
    name: f.name,
    status: 'uploading',
    percent: 0,
    error: '',
  }))
  uploadQueue.value.push(...tasks)
  files.forEach((file, i) => uploadOne(file, tasks[i]))
}

async function uploadZip(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  const task: UploadTask = { key: ++uploadKey, name: file.name, status: 'uploading', percent: 0, error: '' }
  uploadQueue.value.push(task)
  try {
    const { data } = await api.post(`/kbs/${kbId}/documents/upload-zip`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (ev) => {
        if (ev.total) task.percent = Math.round((ev.loaded / ev.total) * 100)
      },
    })
    task.status = 'done'
    task.percent = 100
    message.success(data.detail || 'ZIP 导入完成')
  } catch (err) {
    task.status = 'error'
    task.error = errMsg(err)
    message.error(`ZIP 导入失败：${errMsg(err)}`)
  }
  loadAndWatch()
}

async function uploadOne(file: File, task: UploadTask) {
  const fd = new FormData()
  fd.append('file', file)
  try {
    await api.post(`/kbs/${kbId}/documents/upload`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (ev) => {
        if (ev.total) {
          task.percent = Math.round((ev.loaded / ev.total) * 100)
        }
      },
    })
    task.status = 'done'
    task.percent = 100
    message.success(`「${file.name}」已上传，开始索引`)
  } catch (err) {
    task.status = 'error'
    task.error = errMsg(err)
    message.error(`「${file.name}」上传失败：${errMsg(err)}`)
  }
  loadAndWatch()
}

async function openChunks(d: DocumentItem) {
  chunkDoc.value = d
  chunks.value = []
  chunksLoading.value = true
  try {
    const { data } = await api.get<ChunkItem[]>(`/kbs/${kbId}/documents/${d.id}/chunks`)
    chunks.value = data
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    chunksLoading.value = false
  }
}

// ---------------- 文档预览 ----------------
const previewOpen = ref(false)
const previewDoc = ref<DocumentItem | null>(null)
const previewLoading = ref(false)
const previewUrl = ref('')
const previewText = ref<string | null>(null)

async function openPreview(d: DocumentItem) {
  previewOpen.value = true
  previewDoc.value = d
  previewLoading.value = true
  previewUrl.value = ''
  previewText.value = null
  try {
    const resp = await fetch(`/api/kbs/${kbId}/documents/${d.id}/download`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    if (d.file_type === 'pdf') {
      previewUrl.value = URL.createObjectURL(blob)
    } else if (['txt', 'md', 'html', 'htm', 'csv'].includes(d.file_type)) {
      previewText.value = await blob.text()
    } else {
      previewText.value = null // 不支持的类型
    }
  } catch (e) {
    message.error(`预览失败：${errMsg(e)}`)
    previewOpen.value = false
  } finally {
    previewLoading.value = false
  }
}

async function del(d: DocumentItem) {
  try {
    await api.delete(`/kbs/${kbId}/documents/${d.id}`)
    message.success('文档已移入回收站')
    loadAndWatch()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function restore(d: DocumentItem) {
  try {
    await api.post(`/kbs/${kbId}/documents/${d.id}/restore`)
    message.success('已提交恢复，正在重建索引')
    loadTrash()
    loadAndWatch()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function purge(d: DocumentItem) {
  try {
    await api.post(`/kbs/${kbId}/documents/${d.id}/purge`)
    message.success('已彻底删除')
    loadTrash()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function batchOp(action: 'delete' | 'reindex') {
  if (!selectedIds.value.length) return
  try {
    await api.post(`/kbs/${kbId}/documents/batch`, { action, ids: selectedIds.value })
    message.success(`已对 ${selectedIds.value.length} 个文档执行${action === 'delete' ? '删除（回收站）' : '重建索引'}`)
    selectedIds.value = []
    loadAndWatch()
  } catch (e) {
    message.error(errMsg(e))
  }
}

// ---------------- 版本更新（替换） ----------------
const replaceInput = ref<HTMLInputElement | null>(null)
const replaceTarget = ref<DocumentItem | null>(null)
const replacing = ref(false)

function openReplace(d: DocumentItem) {
  replaceTarget.value = d
  replaceInput.value?.click()
}

function onReplaceSelected(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !replaceTarget.value) return
  const doc = replaceTarget.value
  replaceTarget.value = null
  replacing.value = true
  const fd = new FormData()
  fd.append('file', file)
  api
    .post(`/kbs/${kbId}/documents/${doc.id}/replace`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(() => {
      message.success(`「${doc.filename}」已更新为新版本，正在重新索引`)
      loadAndWatch()
    })
    .catch((err) => {
      message.error(`更新失败：${errMsg(err)}`)
    })
    .finally(() => {
      replacing.value = false
    })
}

async function reindex(d: DocumentItem) {
  try {
    await api.post(`/kbs/${kbId}/documents/${d.id}/reindex`)
    message.success('已提交重建索引')
    loadAndWatch()
  } catch (e) {
    message.error(errMsg(e))
  }
}

// 导出知识库备份（JSON）
const exporting = ref(false)
async function exportKb() {
  exporting.value = true
  try {
    const resp = await fetch(`/api/kbs/${kbId}/documents/export`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `kb_${kbId}_${kb.value?.name || 'export'}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('知识库已导出（JSON 备份）')
  } catch (e) {
    message.error(`导出失败：${errMsg(e)}`)
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.docs-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.upload-queue {
  margin-top: 12px;
  border-top: 1px dashed #e8e8e8;
  padding-top: 8px;
}
.upload-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
}
.upload-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.upload-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.upload-error {
  color: #ff4d4f;
  font-size: 12px;
}
</style>