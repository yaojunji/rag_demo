<template>
  <a-tabs v-model:activeKey="activeTab">
    <!-- ============ 系统概览（仪表盘） ============ -->
    <a-tab-pane key="overview" tab="系统概览">
      <a-row :gutter="[12, 12]">
        <a-col v-for="s in statCards" :key="s.label" :span="6">
          <a-card size="small" :bordered="false">
            <a-statistic :title="s.label" :value="s.value" :value-style="{ fontSize: '22px' }">
              <template #prefix><component :is="s.icon" /></template>
            </a-statistic>
          </a-card>
        </a-col>
      </a-row>
      <a-row style="margin-top: 12px">
        <a-col :span="24">
          <a-card size="small" :bordered="false">
            <a-space>
              <span>模型连通性</span>
              <a-button size="small" type="primary" ghost :loading="mcLoading" @click="runModelCheck">
                <ThunderboltOutlined /> 一键自检
              </a-button>
              <a-tag v-if="mcResult" :color="mcAllOk ? 'success' : 'error'">{{ mcAllOk ? '全部可用' : '存在不可用模型' }}</a-tag>
            </a-space>
            <template v-if="mcResult">
              <a-row :gutter="12" style="margin-top: 12px">
                <a-col :span="12">
                  <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px">对话模型</div>
                  <div v-for="m in (mcResult.chat_models as any[])" :key="m.model" style="margin-bottom: 4px">
                    <a-tag :color="m.ok ? 'success' : 'error'">{{ m.ok ? '✓' : '✗' }}</a-tag>
                    <span style="font-size: 12px">{{ m.model }}</span>
                    <span style="font-size: 12px; color: #999; margin-left: 8px">
                      {{ m.ok ? `${m.latency_ms}ms` : m.error }}
                    </span>
                  </div>
                </a-col>
                <a-col :span="12">
                  <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px">向量模型</div>
                  <div v-for="m in (mcResult.embed_models as any[])" :key="m.model" style="margin-bottom: 4px">
                    <a-tag :color="m.ok ? 'success' : 'error'">{{ m.ok ? '✓' : '✗' }}</a-tag>
                    <span style="font-size: 12px">{{ m.model }}</span>
                    <span style="font-size: 12px; color: #999; margin-left: 8px">
                      {{ m.ok ? `${m.latency_ms}ms` : m.error }}
                    </span>
                  </div>
                </a-col>
              </a-row>
            </template>
          </a-card>
        </a-col>
      </a-row>
      <a-row :gutter="12" style="margin-top: 12px">
        <a-col :span="12">
          <a-card size="small" title="近14天问答趋势" :bordered="false">
            <Chart :option="chatTrendOption" :height="260" />
          </a-card>
        </a-col>
        <a-col :span="12">
          <a-card size="small" title="近14天新增文档" :bordered="false">
            <Chart :option="docTrendOption" :height="260" />
          </a-card>
        </a-col>
        <a-col :span="12">
          <a-card size="small" title="知识库规模 TOP10" :bordered="false">
            <Chart :option="kbOption" :height="260" />
          </a-card>
        </a-col>
        <a-col :span="12">
          <a-card size="small" title="热门问题 TOP10" :bordered="false">
            <Chart :option="topQOption" :height="260" />
          </a-card>
        </a-col>
      </a-row>
    </a-tab-pane>

    <!-- ============ 检索调试 ============ -->
    <a-tab-pane key="rag" tab="检索调试">
      <a-card size="small" :bordered="false">
        <a-space style="width: 100%">
          <a-select v-model:value="dbgKbId" style="width: 200px" placeholder="知识库" :options="kbSelectOptions" />
          <a-input
            v-model:value="dbgQuery"
            style="width: 360px"
            placeholder="输入测试问题，查看检索链路"
            @press-enter="runDebug"
          />
          <a-button type="primary" :loading="dbgLoading" @click="runDebug">运行检索</a-button>
        </a-space>
        <a-alert
          v-if="!dbgResult"
          style="margin-top: 12px"
          type="info"
          show-icon
          message="用于排查“为什么答不好”：按流程查看每一步的命中情况——点击步骤查看该环节详情，命中块标注了“最终入选/后续淘汰”。"
        />
        <template v-if="dbgResult">
          <!-- 流程总览 -->
          <a-steps
            size="small"
            :current="activeStep"
            :items="debugSteps"
            style="margin-top: 16px"
            @change="(i: number) => (activeStep = i)"
          />
          <!-- 每步详情 -->
          <a-divider style="margin: 12px 0 8px" />
          <div class="debug-head">
            <b>{{ debugStepTitle }}</b>
            <span style="color: #999; font-size: 12px">
              <template v-if="activeStep === 0">
                查询文本 → 向量模型 {{ dbgResult.embed_model }} 编码（{{ dbgResult.timings_ms?.vector_ms ?? '-' }}ms）
              </template>
              <template v-else-if="activeStep === 1">
                语义相似度召回（Chroma 余弦距离），共 {{ dbgResult.vector_hits.length }} 条
              </template>
              <template v-else-if="activeStep === 2">
                jieba 分词 + FTS5 BM25 关键词召回，共 {{ dbgResult.keyword_hits.length }} 条
              </template>
              <template v-else-if="activeStep === 3">
                两种召回按排名倒数加权合并（{{ dbgResult.timings_ms?.fuse_ms ?? '-' }}ms）
              </template>
              <template v-else-if="activeStep === 4">
                大模型按相关性精排并剔除无关片段（{{ dbgResult.timings_ms?.rerank_ms ?? '-' }}ms）
              </template>
              <template v-else>
                最终送入 LLM 生成回答的 {{ dbgResult.final_hits.length }} 个片段（即回答底部引用）
              </template>
            </span>
          </div>
          <div class="debug-list">
            <div v-if="activeStep === 0" class="debug-empty">步骤说明：查询先由 {{ dbgResult.embed_model }} 编码为向量（耗时 {{ dbgResult.timings_ms?.vector_ms ?? '-' }}ms），随后并行执行两条召回路径。</div>
            <div v-for="(hit, hi) in debugStepHits" :key="`${activeStep}-${hi}`" class="debug-hit" :style="{ borderLeftColor: hit.in_final ? '#52c41a' : hit.dropped ? '#ff4d4f' : '#1668dc' }">
              <div class="debug-hit-head">
                <b>#{{ hit.chunk_id }}</b>
                <span class="debug-doc">《{{ hit.doc_name }}》</span>
                <span class="debug-kb">kb#{{ hit.kb_id }}</span>
                <span class="debug-score">相关度 {{ hit.score.toFixed(4) }}</span>
                <a-tag v-if="hit.in_final" color="success" size="small">最终入选</a-tag>
                <a-tag v-else-if="hit.dropped" color="error" size="small">后续淘汰</a-tag>
                <a-tag v-else color="blue" size="small">本步入选</a-tag>
              </div>
              <div class="debug-text">{{ hit.text }}</div>
            </div>
            <div v-if="activeStep > 0 && !debugStepHits.length" class="debug-empty">该环节无命中</div>
          </div>
        </template>
      </a-card>
    </a-tab-pane>

    <!-- ============ 内容检索 ============ -->
    <a-tab-pane key="search" tab="内容检索">
      <a-card size="small" :bordered="false">
        <a-space style="width: 100%">
          <a-select v-model:value="csKbId" style="width: 180px" allow-clear placeholder="全部知识库" :options="kbSelectOptions" @change="() => loadContentSearch(1)" />
          <a-input
            v-model:value="csQuery"
            style="width: 340px"
            placeholder="搜索知识库内容（关键词），留空浏览最新分块"
            @press-enter="loadContentSearch(1)"
          />
          <a-button type="primary" :loading="csLoading" @click="loadContentSearch(1)">搜索</a-button>
        </a-space>
        <a-table
          style="margin-top: 12px"
          :data-source="csList.items"
          :columns="csColumns"
          row-key="chunk_id"
          :pagination="{ current: csList.page, pageSize: csList.page_size, total: csList.total, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number) => loadContentSearch(p) }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'source'">
              <div><b>{{ record.doc_name }}</b></div>
              <div style="font-size: 12px; color: #999">《{{ record.kb_name }}》 · 片段 {{ record.chunk_index + 1 }}<template v-if="record.page"> · 第 {{ record.page }} 页</template></div>
            </template>
            <template v-else-if="column.key === 'content'">
              <div style="font-size: 12px; max-width: 520px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical">
                {{ record.content }}
              </div>
            </template>
          </template>
        </a-table>
      </a-card>
    </a-tab-pane>

    <!-- ============ API 集成 ============ -->
    <a-tab-pane key="api" tab="API 集成">
      <a-card size="small" :bordered="false">
        <template #title>API Token（OpenAI 兼容接口）</template>
        <template #extra>
          <a-button type="primary" size="small" @click="openTokenModal"><PlusOutlined /> 新建 Token</a-button>
        </template>
        <a-alert
          type="info"
          show-icon
          style="margin-bottom: 12px"
          message="外部系统可通过标准 OpenAI SDK 调用知识库问答：base_url=http://127.0.0.1:8000/v1，api_key=Token"
        />
        <a-table :data-source="tokens" :columns="tokenColumns" row-key="id" :pagination="false">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'scope'">
              <span v-if="record.kb_ids?.length">{{ record.kb_ids.map((i: number) => kbNames[i] || `#${i}`).join('、') }}</span>
              <span v-else style="color: #999">全部可见库</span>
            </template>
            <template v-else-if="column.key === 'is_active'">
              <a-switch size="small" :checked="record.is_active" @change="() => toggleToken(record)" />
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ fmtTime(record.created_at) }}
            </template>
            <template v-else-if="column.key === 'last_used_at'">
              {{ record.last_used_at ? fmtTime(record.last_used_at) : '从未使用' }}
            </template>
            <template v-else-if="column.key === 'action'">
              <a-popconfirm title="删除该 Token？删除后外部调用立即失效" @confirm="delToken(record)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </template>
          </template>
        </a-table>
      </a-card>
    </a-tab-pane>

    <!-- ============ 系统日志 ============ -->
    <a-tab-pane key="logs" tab="系统日志">
      <a-card size="small" :bordered="false">
        <template #title>运行日志（内存最近 {{ logItems.length }} 条）</template>
        <template #extra>
          <a-space>
            <a-radio-group v-model:value="logLevel" size="small" @change="loadLogs">
              <a-radio-button value="DEBUG">全部</a-radio-button>
              <a-radio-button value="INFO">INFO+</a-radio-button>
              <a-radio-button value="WARNING">WARN+</a-radio-button>
              <a-radio-button value="ERROR">ERROR</a-radio-button>
            </a-radio-group>
            <a-button size="small" :loading="logLoading" @click="loadLogs">
              <ReloadOutlined /> 刷新
            </a-button>
            <a-switch v-model:checked="logAuto" size="small" checked-children="自动" un-checked-children="手动" />
          </a-space>
        </template>
        <div class="log-box chat-scroll">
          <div v-for="(log, i) in logItems" :key="i" class="log-line" :class="`lv-${log.level.toLowerCase()}`">
            <span class="log-time">{{ fmtTimeFull(log.time) }}</span>
            <a-tag :color="logColor(log.level)" size="small" style="margin: 0 6px">{{ log.level }}</a-tag>
            <span class="log-name">{{ log.name }}</span>
            <span class="log-msg">{{ log.message }}</span>
          </div>
          <div v-if="!logItems.length" style="color: #999; padding: 16px">暂无日志</div>
        </div>
      </a-card>
    </a-tab-pane>

    <!-- ============ 反馈管理 ============ -->
    <a-tab-pane key="feedback" tab="回答反馈">
      <a-row :gutter="12" style="margin-bottom: 12px">
        <a-col :span="6"><a-card size="small"><a-statistic title="好评" :value="fbStats?.up ?? 0" value-style="color:#52c41a" /></a-card></a-col>
        <a-col :span="6"><a-card size="small"><a-statistic title="差评" :value="fbStats?.down ?? 0" value-style="color:#ff4d4f" /></a-card></a-col>
        <a-col :span="6"><a-card size="small"><a-statistic title="好评率" :value="fbStats?.up_rate ?? 0" suffix="%" /></a-card></a-col>
        <a-col :span="6"><a-card size="small"><a-statistic title="反馈总数" :value="fbStats?.total ?? 0" /></a-card></a-col>
      </a-row>
      <a-card size="small" :bordered="false">
        <template #title>反馈明细</template>
        <template #extra>
          <a-space>
            <a-radio-group v-model:value="fbFilter" size="small" @change="() => loadFeedback(1)">
              <a-radio-button value="">全部</a-radio-button>
              <a-radio-button value="up">好评</a-radio-button>
              <a-radio-button value="down">差评</a-radio-button>
            </a-radio-group>
          </a-space>
        </template>
        <a-table
          :data-source="fbList.items"
          :columns="fbColumns"
          row-key="id"
          :pagination="{ current: fbList.page, pageSize: fbList.page_size, total: fbList.total, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number) => loadFeedback(p) }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'rating'">
              <a-tag :color="record.rating === 'up' ? 'success' : 'error'">{{ record.rating === 'up' ? '赞' : '踩' }}</a-tag>
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ fmtTimeFull(record.created_at) }}
            </template>
          </template>
        </a-table>
      </a-card>
    </a-tab-pane>

    <!-- ============ 用户管理 ============ -->
    <a-tab-pane key="users" tab="用户管理">
      <a-card size="small" :bordered="false">
        <template #title>用户（{{ users.length }}）</template>
        <template #extra>
          <a-button type="primary" size="small" @click="userModalOpen = true"><PlusOutlined /> 新建用户</a-button>
        </template>
        <a-table :data-source="users" :columns="userColumns" row-key="id" :pagination="false">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'role'">
              <a-tag :color="roleColor[record.role]">{{ roleText[record.role] }}</a-tag>
            </template>
            <template v-else-if="column.key === 'tenant'">
              {{ tenantName(record.tenant_id) }}
            </template>
            <template v-else-if="column.key === 'is_active'">
              <a-switch size="small" :checked="record.is_active" @change="() => toggleActive(record)" />
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ fmtTime(record.created_at) }}
            </template>
            <template v-else-if="column.key === 'action'">
              <a-space>
                <a-button size="small" @click="openEditUser(record)">编辑</a-button>
                <a-button size="small" @click="openResetPwd(record)">重置密码</a-button>
                <a-popconfirm :title="`删除用户 ${record.username}？`" @confirm="delUser(record)">
                  <a-button size="small" danger>删除</a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </template>
        </a-table>
      </a-card>
    </a-tab-pane>

    <!-- ============ 租户管理 ============ -->
    <a-tab-pane key="tenants" tab="租户管理">
      <a-card size="small" :bordered="false">
        <template #title>租户（{{ tenants.length }}）</template>
        <template #extra>
          <a-button type="primary" size="small" @click="tenantModalOpen = true"><PlusOutlined /> 新建租户</a-button>
        </template>
        <a-table :data-source="tenants" :columns="tenantColumns" row-key="id" :pagination="false">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'created_at'">
              {{ fmtTime(record.created_at) }}
            </template>
            <template v-else-if="column.key === 'action'">
              <a-popconfirm title="删除租户？" @confirm="delTenant(record)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </template>
          </template>
        </a-table>
      </a-card>
    </a-tab-pane>

    <!-- ============ 审计日志 ============ -->
    <a-tab-pane key="audit" tab="审计日志">
      <a-card size="small" :bordered="false">
        <a-table
          :data-source="audits.items"
          :columns="auditColumns"
          row-key="id"
          :pagination="{ current: audits.page, pageSize: audits.page_size, total: audits.total, showTotal: (t: number) => `共 ${t} 条`, onChange: loadAudits }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'created_at'">
              {{ fmtTimeFull(record.created_at) }}
            </template>
            <template v-else-if="column.key === 'action'">
              <a-tag>{{ record.action }}</a-tag>
            </template>
            <template v-else-if="column.key === 'resource'">
              {{ record.resource_type }}:{{ record.resource_id }}
            </template>
          </template>
        </a-table>
      </a-card>
    </a-tab-pane>
  </a-tabs>

  <!-- 新建用户 -->
  <a-modal title="新建用户" v-model:open="userModalOpen" :confirm-loading="savingUser" @ok="createUser" destroy-on-close>
    <a-form ref="userFormRef" :model="userForm" :label-col="{ span: 5 }">
      <a-form-item label="用户名" name="username" :rules="[{ required: true, message: '请输入用户名' }]">
        <a-input v-model:value="userForm.username" placeholder="2-64 位字母数字" />
      </a-form-item>
      <a-form-item label="初始密码" name="password" :rules="[{ required: true, min: 6, message: '至少 6 位' }]">
        <a-input-password v-model:value="userForm.password" />
      </a-form-item>
      <a-form-item label="姓名" name="display_name">
        <a-input v-model:value="userForm.display_name" />
      </a-form-item>
      <a-form-item label="角色" name="role">
        <a-select v-model:value="userForm.role" :options="roleOptions" />
      </a-form-item>
      <a-form-item label="所属租户" name="tenant_id">
        <a-select v-model:value="userForm.tenant_id" allow-clear placeholder="不选则全局" :options="tenantOptions" />
      </a-form-item>
    </a-form>
  </a-modal>

  <!-- 新建租户 -->
  <a-modal title="新建租户" v-model:open="tenantModalOpen" :confirm-loading="savingTenant" @ok="createTenant" destroy-on-close>
    <a-form ref="tenantFormRef" :model="tenantForm" :label-col="{ span: 5 }">
      <a-form-item label="租户名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
        <a-input v-model:value="tenantForm.name" />
      </a-form-item>
      <a-form-item label="描述" name="description">
        <a-textarea v-model:value="tenantForm.description" :rows="2" />
      </a-form-item>
    </a-form>
  </a-modal>

  <!-- 编辑用户（权限设置） -->
  <a-modal title="编辑用户" v-model:open="editUserOpen" :confirm-loading="savingEditUser" @ok="submitEditUser" destroy-on-close>
    <a-form ref="editUserFormRef" :model="editUserForm" :label-col="{ span: 5 }">
      <a-form-item label="用户名">
        <a-input :value="editUserForm.username" disabled />
      </a-form-item>
      <a-form-item label="姓名" name="display_name">
        <a-input v-model:value="editUserForm.display_name" />
      </a-form-item>
      <a-form-item label="角色" name="role">
        <a-select v-model:value="editUserForm.role" :options="roleOptions" />
      </a-form-item>
      <a-form-item label="所属租户" name="tenant_id">
        <a-select v-model:value="editUserForm.tenant_id" allow-clear placeholder="不选则全局" :options="tenantOptions" />
      </a-form-item>
      <a-form-item label="账号状态" name="is_active">
        <a-switch v-model:checked="editUserForm.is_active" checked-children="启用" un-checked-children="禁用" />
      </a-form-item>
    </a-form>
  </a-modal>

  <!-- 重置密码 -->
  <a-modal title="重置密码" v-model:open="pwdOpen" @ok="confirmResetPwd" destroy-on-close>
    <p>{{ pwdTarget?.username }}</p>
    <a-input-password v-model:value="pwdValue" placeholder="新密码（至少 6 位）" />
  </a-modal>

  <!-- 新建 API Token -->
  <a-modal title="新建 API Token" v-model:open="tokenModalOpen" :confirm-loading="tokenSaving" @ok="createToken" destroy-on-close>
    <a-form :label-col="{ span: 5 }">
      <a-form-item label="名称" required>
        <a-input v-model:value="tokenForm.name" placeholder="如：办公系统接入" />
      </a-form-item>
      <a-form-item label="绑定用户">
        <a-select
          v-model:value="tokenForm.user_id"
          placeholder="默认当前管理员"
          allow-clear
          :options="users.map((u) => ({ value: u.id, label: `${u.username}（${roleText[u.role]}）` }))"
        />
      </a-form-item>
      <a-form-item label="知识库范围">
        <a-select
          v-model:value="tokenForm.kb_ids"
          mode="multiple"
          allow-clear
          placeholder="不选则可用该用户可见的全部知识库"
          :options="kbSelectOptions"
        />
      </a-form-item>
    </a-form>
  </a-modal>

  <!-- Token 创建成功（明文仅展示一次） -->
  <a-modal title="Token 创建成功（请立即保存，仅此一次可见）" v-model:open="tokenResultOpen" :footer="null" destroy-on-close>
    <a-textarea :value="tokenResult" :rows="3" read-only style="font-family: monospace" />
    <div style="margin-top: 8px">
      <a-button type="primary" size="small" @click="copyToken">复制 Token</a-button>
    </div>
    <a-divider style="margin: 12px 0" />
    <div style="font-size: 12px; color: #666">
      <p>Python 调用示例：</p>
      <pre style="background: #f6f8fa; padding: 8px; border-radius: 6px; overflow: auto">from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="&lt;TOKEN&gt;")
resp = client.chat.completions.create(
    model="qwen-max",
    messages=[{"role": "user", "content": "姚俊吉的技术栈？"}],
)
print(resp.choices[0].message.content)
# resp.choices[0].message.citations  # 引用列表</pre>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  CommentOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'
import { api, errMsg } from '../api'
import { fmtTime, fmtTimeFull } from '../utils/time'
import Chart from '../components/Chart.vue'
import type {
  AuditItem,
  DashboardOut,
  FeedbackStats,
  KnowledgeBase,
  Page,
  RagDebugOut,
  SystemStats,
  Tenant,
  User,
} from '../types'

const activeTab = ref('overview')
const stats = ref<DashboardOut | null>(null)
const users = ref<User[]>([])
const tenants = ref<Tenant[]>([])
const audits = ref<Page<AuditItem>>({ total: 0, page: 1, page_size: 20, items: [] })
const kbs = ref<KnowledgeBase[]>([])

const statCards = computed(() => {
  const t = stats.value?.totals
  return [
    { label: '知识库', value: t?.knowledge_bases ?? '-', icon: DatabaseOutlined },
    { label: '文档', value: t?.documents ?? '-', icon: FileTextOutlined },
    { label: '分块', value: t?.chunks ?? '-', icon: FileTextOutlined },
    { label: '问答消息', value: t?.chat_messages ?? '-', icon: CommentOutlined },
    { label: '用户', value: t?.users ?? '-', icon: UserOutlined },
    { label: '租户', value: t?.tenants ?? '-', icon: TeamOutlined },
    { label: '审计记录', value: t?.audit_logs ?? '-', icon: RobotOutlined },
    { label: '版本', value: t?.version ?? '-', icon: RobotOutlined },
  ]
})

const mcAllOk = computed(() => {
  if (!mcResult.value) return false
  const all = [...(mcResult.value.chat_models as { ok: boolean }[]), ...(mcResult.value.embed_models as { ok: boolean }[])]
  return all.length > 0 && all.every((m) => m.ok)
})

const chatTrendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 16, top: 24, bottom: 24 },
  xAxis: { type: 'category', data: (stats.value?.chat_trend || []).map((p) => p.date.slice(5)), axisLabel: { fontSize: 10 } },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{ type: 'line', smooth: true, areaStyle: { opacity: 0.15 }, data: (stats.value?.chat_trend || []).map((p) => p.count), itemStyle: { color: '#1668dc' } }],
}))

const docTrendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 16, top: 24, bottom: 24 },
  xAxis: { type: 'category', data: (stats.value?.doc_trend || []).map((p) => p.date.slice(5)), axisLabel: { fontSize: 10 } },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{ type: 'bar', data: (stats.value?.doc_trend || []).map((p) => p.count), itemStyle: { color: '#52c41a' } }],
}))

const kbOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 90, right: 24, top: 16, bottom: 24 },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: { type: 'category', data: (stats.value?.kb_stats || []).map((k) => k.kb_name).reverse(), axisLabel: { fontSize: 10 } },
  series: [
    { name: '分块', type: 'bar', data: (stats.value?.kb_stats || []).map((k) => k.chunks).reverse(), itemStyle: { color: '#1668dc' } },
    { name: '文档', type: 'bar', data: (stats.value?.kb_stats || []).map((k) => k.docs).reverse(), itemStyle: { color: '#52c41a' } },
  ],
}))

const topQOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 120, right: 24, top: 16, bottom: 24 },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: { type: 'category', data: (stats.value?.top_questions || []).map((q) => q.question).reverse(), axisLabel: { fontSize: 10 } },
  series: [{ type: 'bar', data: (stats.value?.top_questions || []).map((q) => q.count).reverse(), itemStyle: { color: '#fa8c16' } }],
}))

// ---------------- 检索调试（流程可视化） ----------------
const dbgKbId = ref<number | null>(null)
const dbgQuery = ref('')
const dbgLoading = ref(false)
const dbgResult = ref<RagDebugOut | null>(null)
const activeStep = ref(5)
const kbSelectOptions = computed(() => kbs.value.map((k) => ({ value: k.id, label: k.name })))

// 六步流程条
const debugSteps = computed(() => {
  const r = dbgResult.value
  if (!r) return []
  return [
    { title: '查询向量化', description: `${r.embed_model} · ${r.timings_ms?.vector_ms ?? '-'}ms` },
    { title: '向量检索', description: `${r.vector_hits.length} 条` },
    { title: '关键词检索', description: `${r.keyword_hits.length} 条` },
    { title: 'RRF 融合', description: `${r.fused_hits.length} 条 · ${r.timings_ms?.fuse_ms ?? '-'}ms` },
    { title: 'LLM 重排', description: `${r.reranked_hits.length} 条 · ${r.timings_ms?.rerank_ms ?? '-'}ms` },
    { title: '最终上下文', description: `${r.final_hits.length} 条送入 LLM` },
  ]
})

const debugStepTitle = computed(() => {
  return ['① 查询向量化', '② 向量检索', '③ 关键词检索', '④ RRF 融合', '⑤ LLM 重排', '⑥ 最终上下文'][activeStep.value] || ''
})

// 当前步骤的命中详情 + 入选/淘汰标记
const debugStepHits = computed(() => {
  const r = dbgResult.value
  if (!r || activeStep.value === 0) return []
  const source =
    activeStep.value === 1 ? r.vector_hits :
    activeStep.value === 2 ? r.keyword_hits :
    activeStep.value === 3 ? r.fused_hits :
    activeStep.value === 4 ? r.reranked_hits :
    r.final_hits
  const finalIds = new Set(r.final_hits.map((h) => h.chunk_id))
  const laterIds = new Set(
    activeStep.value < 3 ? r.fused_hits.map((h) => h.chunk_id) : []
  )
  const rerankIds = new Set(
    activeStep.value < 4 ? r.reranked_hits.map((h) => h.chunk_id) : []
  )
  return source.map((h) => ({
    ...h,
    in_final: finalIds.has(h.chunk_id),
    dropped:
      activeStep.value === 1 ? !laterIds.has(h.chunk_id) && !finalIds.has(h.chunk_id) :
      activeStep.value === 2 ? !laterIds.has(h.chunk_id) && !finalIds.has(h.chunk_id) :
      activeStep.value === 3 ? !rerankIds.has(h.chunk_id) && !finalIds.has(h.chunk_id) :
      activeStep.value === 4 ? !finalIds.has(h.chunk_id) :
      false,
  }))
})

async function runDebug() {
  if (!dbgKbId.value || !dbgQuery.value.trim()) {
    message.warning('请选择知识库并输入问题')
    return
  }
  dbgLoading.value = true
  try {
    const { data } = await api.post<RagDebugOut>('/admin/rag-debug', {
      kb_id: dbgKbId.value,
      query: dbgQuery.value.trim(),
    })
    dbgResult.value = data
    activeStep.value = 5 // 默认展示最终上下文
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    dbgLoading.value = false
  }
}

// ---------------- 内容检索 ----------------
const csKbId = ref<number | undefined>(undefined)
const csQuery = ref('')
const csLoading = ref(false)
const csList = ref<Page<Record<string, unknown>>>({ total: 0, page: 1, page_size: 20, items: [] })
const csColumns = [
  { title: '来源', key: 'source', width: 240 },
  { title: '内容', key: 'content' },
]

async function loadContentSearch(page = 1) {
  csLoading.value = true
  try {
    const params: Record<string, unknown> = { page, page_size: 20 }
    if (csQuery.value.trim()) params.q = csQuery.value.trim()
    if (csKbId.value !== undefined && csKbId.value !== null) params.kb_id = csKbId.value
    const { data } = await api.get<Page<Record<string, unknown>>>('/admin/chunks/search', { params })
    csList.value = data
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    csLoading.value = false
  }
}

// ---------------- 模型自检 ----------------
const mcOpen = ref(false)
const mcLoading = ref(false)
const mcResult = ref<Record<string, unknown> | null>(null)

async function runModelCheck() {
  mcLoading.value = true
  mcResult.value = null
  try {
    const { data } = await api.post<Record<string, unknown>>('/admin/model-check')
    mcResult.value = data
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    mcLoading.value = false
  }
}

// ---------------- API Token 管理 ----------------
const tokens = ref<Record<string, unknown>[]>([])
const tokenModalOpen = ref(false)
const tokenSaving = ref(false)
const tokenResultOpen = ref(false)
const tokenResult = ref('')
const tokenForm = reactive({ name: '', user_id: undefined as number | undefined, kb_ids: [] as number[] })
const kbNames = computed(() => Object.fromEntries(kbs.value.map((k) => [k.id, k.name])))
const tokenColumns = [
  { title: 'ID', dataIndex: 'id', width: 60 },
  { title: '名称', dataIndex: 'name' },
  { title: '绑定用户', dataIndex: 'username', width: 110 },
  { title: '知识库范围', key: 'scope' },
  { title: '状态', key: 'is_active', width: 80 },
  { title: '创建时间', key: 'created_at', width: 150 },
  { title: '最后使用', key: 'last_used_at', width: 150 },
  { title: '操作', key: 'action', width: 80 },
]

async function loadTokens() {
  try {
    const { data } = await api.get('/admin/api-tokens')
    tokens.value = data as Record<string, unknown>[]
  } catch (e) {
    message.error(errMsg(e))
  }
}

function openTokenModal() {
  tokenForm.name = ''
  tokenForm.user_id = undefined
  tokenForm.kb_ids = []
  tokenModalOpen.value = true
}

async function createToken() {
  if (!tokenForm.name.trim()) {
    message.warning('请输入名称')
    return
  }
  tokenSaving.value = true
  try {
    const { data } = await api.post('/admin/api-tokens', {
      name: tokenForm.name.trim(),
      user_id: tokenForm.user_id,
      kb_ids: tokenForm.kb_ids,
    })
    tokenResult.value = data.token
    tokenModalOpen.value = false
    tokenResultOpen.value = true
    loadTokens()
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    tokenSaving.value = false
  }
}

async function toggleToken(record: Record<string, unknown>) {
  try {
    await api.post(`/admin/api-tokens/${record.id}/toggle`)
    loadTokens()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function delToken(record: Record<string, unknown>) {
  try {
    await api.delete(`/admin/api-tokens/${record.id}`)
    message.success('已删除')
    loadTokens()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(tokenResult.value)
    message.success('已复制')
  } catch {
    message.error('复制失败，请手动选择复制')
  }
}

// ---------------- 系统日志 ----------------
const logItems = ref<Record<string, string>[]>([])
const logLevel = ref('INFO')
const logLoading = ref(false)
const logAuto = ref(true)
let logTimer: ReturnType<typeof setInterval> | null = null

function logColor(level: string): string {
  return { DEBUG: 'default', INFO: 'blue', WARNING: 'orange', ERROR: 'red', CRITICAL: 'red' }[level] || 'default'
}

async function loadLogs() {
  logLoading.value = true
  try {
    const { data } = await api.get('/admin/logs', { params: { level: logLevel.value, limit: 300 } })
    logItems.value = data.items as Record<string, string>[]
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    logLoading.value = false
  }
}

watch(logAuto, (auto) => {
  if (logTimer) {
    clearInterval(logTimer)
    logTimer = null
  }
  if (auto) {
    loadLogs()
    logTimer = setInterval(loadLogs, 5000)
  }
})
onBeforeUnmount(() => {
  if (logTimer) clearInterval(logTimer)
})

// ---------------- 反馈管理 ----------------
const fbStats = ref<FeedbackStats | null>(null)
const fbFilter = ref('')
const fbList = ref<Page<Record<string, unknown>>>({ total: 0, page: 1, page_size: 20, items: [] })
const fbColumns = [
  { title: 'ID', dataIndex: 'id', width: 60 },
  { title: '评价', key: 'rating', width: 70 },
  { title: '用户', dataIndex: 'username', width: 100 },
  { title: '问题', dataIndex: 'question', width: 200, ellipsis: true },
  { title: 'AI 回答', dataIndex: 'answer', ellipsis: true },
  { title: '备注', dataIndex: 'comment', width: 150, ellipsis: true },
  { title: '时间', key: 'created_at', width: 150 },
]

async function loadFeedback(page = 1) {
  try {
    const params: Record<string, unknown> = { page, page_size: 20 }
    if (fbFilter.value) params.rating = fbFilter.value
    const { data } = await api.get<Page<Record<string, unknown>>>('/admin/feedback', { params })
    fbList.value = data
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function loadFbStats() {
  try {
    const { data } = await api.get<FeedbackStats>('/admin/feedback/stats')
    fbStats.value = data
  } catch (e) {
    message.error(errMsg(e))
  }
}

// ---------------- 用户 / 租户 / 审计 ----------------
const roleText: Record<string, string> = { admin: '管理员', editor: '编辑', viewer: '只读' }
const roleColor: Record<string, string> = { admin: 'red', editor: 'blue', viewer: 'default' }
const roleOptions = [
  { value: 'admin', label: '管理员' },
  { value: 'editor', label: '编辑（可管理知识库）' },
  { value: 'viewer', label: '只读（仅可问答）' },
]
const tenantOptions = computed(() => tenants.value.map((t) => ({ value: t.id, label: t.name })))
const userColumns = [
  { title: 'ID', dataIndex: 'id', width: 60 },
  { title: '用户名', dataIndex: 'username' },
  { title: '姓名', dataIndex: 'display_name' },
  { title: '角色', key: 'role', width: 90 },
  { title: '租户', key: 'tenant', width: 130 },
  { title: '状态', key: 'is_active', width: 90 },
  { title: '创建时间', key: 'created_at', width: 150 },
  { title: '操作', key: 'action', width: 200 },
]
const tenantColumns = [
  { title: 'ID', dataIndex: 'id', width: 80 },
  { title: '名称', dataIndex: 'name' },
  { title: '描述', dataIndex: 'description' },
  { title: '创建时间', key: 'created_at', width: 160 },
  { title: '操作', key: 'action', width: 100 },
]
const auditColumns = [
  { title: '时间', key: 'created_at', width: 165 },
  { title: '用户', dataIndex: 'username', width: 110 },
  { title: '动作', key: 'action', width: 130 },
  { title: '资源', key: 'resource', width: 140 },
  { title: '详情', dataIndex: 'detail', ellipsis: true },
  { title: 'IP', dataIndex: 'ip', width: 130 },
]

const userModalOpen = ref(false)
const tenantModalOpen = ref(false)
const savingUser = ref(false)
const savingTenant = ref(false)
const pwdTarget = ref<User | null>(null)
const pwdValue = ref('')
const pwdOpen = computed({
  get: () => !!pwdTarget.value,
  set: (v: boolean) => {
    if (!v) pwdTarget.value = null
  },
})
const userFormRef = ref()
const tenantFormRef = ref()
const userForm = reactive({ username: '', password: '', display_name: '', role: 'viewer', tenant_id: undefined as number | undefined })
const tenantForm = reactive({ name: '', description: '' })
const editUserOpen = ref(false)
const savingEditUser = ref(false)
const editUserFormRef = ref()
const editUserId = ref<number | null>(null)
const editUserForm = reactive({
  username: '',
  display_name: '',
  role: 'viewer',
  tenant_id: undefined as number | undefined,
  is_active: true,
})

function tenantName(id: number | null) {
  if (!id) return '全局'
  return tenants.value.find((t) => t.id === id)?.name || String(id)
}

async function loadAll() {
  try {
    const [d, k] = await Promise.all([api.get<DashboardOut>('/admin/dashboard'), api.get<KnowledgeBase[]>('/kbs')])
    stats.value = d.data
    kbs.value = k.data
    if (dbgKbId.value === null && k.data.length) dbgKbId.value = k.data[0].id
  } catch (e) {
    message.error(errMsg(e))
  }
}
async function loadUsers() {
  try {
    const { data } = await api.get<User[]>('/admin/users')
    users.value = data
  } catch (e) {
    message.error(errMsg(e))
  }
}
async function loadTenants() {
  try {
    const { data } = await api.get<Tenant[]>('/admin/tenants')
    tenants.value = data
  } catch (e) {
    message.error(errMsg(e))
  }
}
async function loadAudits(page = 1, pageSize = 20) {
  try {
    const { data } = await api.get<Page<AuditItem>>('/admin/audit-logs', { params: { page, page_size: pageSize } })
    audits.value = data
  } catch (e) {
    message.error(errMsg(e))
  }
}

onMounted(() => {
  loadAll()
  loadUsers()
  loadTenants()
  loadAudits()
  loadFeedback()
  loadFbStats()
  loadContentSearch()
  loadTokens()
  if (logAuto.value) loadLogs()
})
watch(activeTab, (tab) => {
  if (tab === 'overview') loadAll()
  if (tab === 'feedback') {
    loadFeedback()
    loadFbStats()
  }
})

async function createUser() {
  try {
    await userFormRef.value.validateFields()
  } catch {
    return
  }
  savingUser.value = true
  try {
    await api.post('/admin/users', { ...userForm })
    message.success('用户已创建')
    userModalOpen.value = false
    loadUsers()
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    savingUser.value = false
  }
}

async function toggleActive(u: User) {
  try {
    await api.put(`/admin/users/${u.id}`, { is_active: !u.is_active })
    loadUsers()
  } catch (e) {
    message.error(errMsg(e))
  }
}

function openEditUser(u: User) {
  editUserId.value = u.id
  editUserForm.username = u.username
  editUserForm.display_name = u.display_name
  editUserForm.role = u.role
  editUserForm.tenant_id = u.tenant_id ?? undefined
  editUserForm.is_active = u.is_active
  editUserOpen.value = true
}

async function submitEditUser() {
  savingEditUser.value = true
  try {
    const payload: Record<string, unknown> = {
      display_name: editUserForm.display_name,
      role: editUserForm.role,
      is_active: editUserForm.is_active,
    }
    if (editUserForm.tenant_id !== undefined) payload.tenant_id = editUserForm.tenant_id
    else payload.tenant_id = null
    await api.put(`/admin/users/${editUserId.value}`, payload)
    message.success('用户权限已更新')
    editUserOpen.value = false
    loadUsers()
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    savingEditUser.value = false
  }
}

function openResetPwd(u: User) {
  pwdTarget.value = u
  pwdValue.value = ''
}

async function confirmResetPwd() {
  if (!pwdTarget.value) return
  if (pwdValue.value.length < 6) {
    message.warning('新密码至少 6 位')
    return
  }
  try {
    await api.put(`/admin/users/${pwdTarget.value.id}`, { password: pwdValue.value })
    message.success('密码已重置')
    pwdTarget.value = null
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function delUser(u: User) {
  try {
    await api.delete(`/admin/users/${u.id}`)
    message.success('已删除')
    loadUsers()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function createTenant() {
  try {
    await tenantFormRef.value.validateFields()
  } catch {
    return
  }
  savingTenant.value = true
  try {
    await api.post('/admin/tenants', { ...tenantForm })
    message.success('租户已创建')
    tenantModalOpen.value = false
    loadTenants()
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    savingTenant.value = false
  }
}

async function delTenant(t: Tenant) {
  try {
    await api.delete(`/admin/tenants/${t.id}`)
    message.success('已删除')
    loadTenants()
  } catch (e) {
    message.error(errMsg(e))
  }
}
</script>

<style scoped>
/* 检索调试：流程详情 */
.debug-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.debug-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 460px;
  overflow: auto;
}
.debug-hit {
  padding: 8px 12px;
  background: #fafbfc;
  border-radius: 6px;
  border-left: 3px solid #1668dc;
}
html[data-theme='dark'] .debug-hit {
  background: #1d1d24;
}
.debug-hit-head {
  font-size: 12px;
  color: #666;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.debug-doc {
  color: #333;
  font-weight: 500;
}
html[data-theme='dark'] .debug-doc {
  color: #ccc;
}
.debug-kb {
  color: #999;
}
.debug-score {
  color: #8c8c8c;
}
.debug-text {
  font-size: 12px;
  margin-top: 4px;
  color: #555;
}
html[data-theme='dark'] .debug-text {
  color: #aaa;
}
.debug-empty {
  color: #999;
  font-size: 12px;
  padding: 12px 0;
}
.log-box {
  background: #fafbfc;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 8px 12px;
  max-height: 560px;
  overflow: auto;
  font-family: Consolas, Monaco, monospace;
}
.log-line {
  font-size: 12px;
  line-height: 1.7;
  display: flex;
  align-items: baseline;
  border-bottom: 1px dashed #f0f0f0;
  padding: 2px 0;
}
.log-line:last-child {
  border-bottom: none;
}
.log-time {
  color: #999;
  flex-shrink: 0;
}
.log-name {
  color: #8c8c8c;
  flex-shrink: 0;
  margin-right: 8px;
}
.log-msg {
  word-break: break-all;
}
.lv-error .log-msg {
  color: #ff4d4f;
}
.lv-warning .log-msg {
  color: #fa8c16;
}
.lv-debug .log-msg {
  color: #bbb;
}
</style>