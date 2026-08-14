<template>
  <a-card title="知识库管理" :bordered="false">
    <template #extra>
      <a-space>
        <a-upload :show-upload-list="false" :custom-request="importBackup">
          <a-button :loading="importing"><UploadOutlined /> 导入备份</a-button>
        </a-upload>
        <a-button type="primary" @click="openModal()">
          <template #icon><PlusOutlined /></template>
          新建知识库
        </a-button>
      </a-space>
    </template>

    <a-table
      :data-source="kbs"
      :columns="columns"
      :loading="loading"
      row-key="id"
      :pagination="false"
      :custom-row="rowProps"
      :row-class-name="() => 'kb-row'"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'">
          <div class="kb-name">{{ record.name }}</div>
          <div class="kb-desc">{{ record.description || '—' }}</div>
        </template>
        <template v-else-if="column.key === 'doc_count'">
          <a-tag color="blue">{{ record.doc_count }}</a-tag>
        </template>
        <template v-else-if="column.key === 'chunk_count'">
          <a-tag color="geekblue">{{ record.chunk_count }}</a-tag>
        </template>
        <template v-else-if="column.key === 'chunk_param'">
          <span class="kb-desc">{{ record.chunk_size }} / 重叠 {{ record.chunk_overlap }}</span>
        </template>
        <template v-else-if="column.key === 'created_at'">
          {{ fmtTime(record.created_at) }}
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space @click.stop>
            <a-button type="link" size="small" @click="goDocs(record)">
              <template #icon><FolderOpenOutlined /></template>
              管理
            </a-button>
            <a-tooltip title="克隆知识库（复制配置与文档）">
              <a-button size="small" @click="cloneKb(record)">
                <template #icon><CopyOutlined /></template>
              </a-button>
            </a-tooltip>
            <a-button size="small" @click="openModal(record)">
              <template #icon><EditOutlined /></template>
            </a-button>
            <a-popconfirm title="删除知识库将清除全部索引，确认？" @confirm="del(record)">
              <a-button size="small" danger>
                <template #icon><DeleteOutlined /></template>
              </a-button>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>
  </a-card>

  <a-modal
    :title="editing ? '编辑知识库' : '新建知识库'"
    v-model:open="modalOpen"
    :confirm-loading="saving"
    @ok="submit"
    destroy-on-close
  >
    <a-form ref="formRef" :model="form" :label-col="{ span: 5 }">
      <a-form-item label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
        <a-input v-model:value="form.name" placeholder="如：员工制度手册" />
      </a-form-item>
      <a-form-item label="描述" name="description">
        <a-textarea v-model:value="form.description" :rows="2" placeholder="知识库用途说明" />
      </a-form-item>
      <a-form-item label="切块大小" name="chunk_size">
        <a-input-number v-model:value="form.chunk_size" :min="100" :max="4000" />
      </a-form-item>
      <a-form-item label="重叠" name="chunk_overlap">
        <a-input-number v-model:value="form.chunk_overlap" :min="0" :max="1000" />
      </a-form-item>
      <a-form-item label="快捷问题" name="welcome_questions">
        <a-textarea
          v-model:value="form.welcome_questions"
          :rows="3"
          placeholder="每行一个，用于问答页欢迎卡片引导（最多 8 个）"
        />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { CopyOutlined, DeleteOutlined, EditOutlined, FolderOpenOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { fmtTime } from '../utils/time'
import { api, errMsg } from '../api'
import type { KnowledgeBase } from '../types'

const router = useRouter()
const kbs = ref<KnowledgeBase[]>([])
const loading = ref(false)
const modalOpen = ref(false)
const saving = ref(false)
const editing = ref<KnowledgeBase | null>(null)
const formRef = ref()
const form = reactive({
  name: '',
  description: '',
  chunk_size: 800,
  chunk_overlap: 120,
  welcome_questions: '',
})

const columns = [
  { title: 'ID', dataIndex: 'id', width: 70 },
  { title: '名称', key: 'name' },
  { title: '文档数', key: 'doc_count', width: 100 },
  { title: '分块数', key: 'chunk_count', width: 100 },
  { title: '切分参数', key: 'chunk_param', width: 140 },
  { title: '创建时间', key: 'created_at', width: 160 },
  { title: '操作', key: 'action', width: 150 },
]

// 时间显示统一走 utils/time（UTC→本地）

async function load() {
  loading.value = true
  try {
    const { data } = await api.get<KnowledgeBase[]>('/kbs')
    kbs.value = data
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
load()

function openModal(kb?: KnowledgeBase) {
  editing.value = kb || null
  form.name = kb?.name || ''
  form.description = kb?.description || ''
  form.chunk_size = kb?.chunk_size ?? 800
  form.chunk_overlap = kb?.chunk_overlap ?? 120
  form.welcome_questions = (kb?.welcome_questions || []).join('\n')
  modalOpen.value = true
}

async function submit() {
  try {
    await formRef.value.validateFields()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name,
      description: form.description,
      chunk_size: form.chunk_size,
      chunk_overlap: form.chunk_overlap,
      welcome_questions: form.welcome_questions
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
        .slice(0, 8),
    }
    if (editing.value) {
      await api.put(`/kbs/${editing.value.id}`, payload)
      message.success('知识库已更新')
    } else {
      await api.post('/kbs', payload)
      message.success('知识库已创建')
    }
    modalOpen.value = false
    load()
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

async function del(kb: KnowledgeBase) {
  try {
    await api.delete(`/kbs/${kb.id}`)
    message.success(`知识库「${kb.name}」已删除`)
    load()
  } catch (e) {
    message.error(errMsg(e))
  }
}

// 克隆知识库
const cloning = ref(false)
async function cloneKb(kb: KnowledgeBase) {
  const name = window.prompt('克隆后的知识库名称：', `${kb.name}（克隆）`)
  if (!name) return
  cloning.value = true
  try {
    const { data } = await api.post('/admin/kb-clone', { source_kb_id: kb.id, name: name.trim() })
    message.success(`克隆成功：${data.name}（${data.documents} 个文档，正在重建索引）`)
    load()
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    cloning.value = false
  }
}

// 导入备份（JSON）
const importing = ref(false)
function importBackup(opt: { file: File; onSuccess: () => void; onError: (e: Error) => void }) {
  const fd = new FormData()
  fd.append('file', opt.file)
  importing.value = true
  api
    .post('/admin/kb-import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => {
      message.success(`导入成功：${r.data.name}（${r.data.doc_count} 文档 / ${r.data.chunk_count} 分块）`)
      opt.onSuccess()
      load()
    })
    .catch((e) => {
      message.error(`导入失败：${errMsg(e)}`)
      opt.onError(e as Error)
    })
    .finally(() => {
      importing.value = false
    })
}

function goDocs(record: KnowledgeBase) {
  router.push(`/kbs/${record.id}`)
}

// antdv Table 无 row-click 事件，用 customRow 绑定行点击
function rowProps(record: KnowledgeBase) {
  return {
    onClick: () => goDocs(record),
    style: { cursor: 'pointer' },
  }
}
</script>

<style scoped>
.kb-name {
  font-weight: 600;
}
.kb-desc {
  color: #999;
  font-size: 12px;
}
</style>