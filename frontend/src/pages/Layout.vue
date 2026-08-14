<template>
  <a-layout class="app-layout">
    <a-layout-sider theme="dark" :width="216">
      <div class="brand">
        <RobotOutlined class="brand-icon" />
        <span>KnowHub 知枢</span>
      </div>
      <a-menu theme="dark" mode="inline" :selected-keys="[selectedKey]" :items="menuItems" @click="onMenuClick" />
    </a-layout-sider>
    <a-layout>
      <a-layout-header class="app-header">
        <a-space>
          <a-button
            type="text"
            size="small"
            :icon="h(BulbOutlined)"
            @click="toggleDark()"
          />
          <a-badge :count="unreadCount" :offset="[-4, 4]" size="small">
            <a-dropdown placement="bottomRight">
              <a-button type="text" size="small" :icon="h(BellOutlined)" />
              <template #overlay>
                <div class="notify-panel">
                  <div class="notify-head">
                    <span>通知</span>
                    <a-button v-if="unreadCount" type="link" size="small" @click="markAllRead()">全部已读</a-button>
                  </div>
                  <div v-if="!notifications.length" style="padding: 24px; text-align: center; color: #999; font-size: 12px">
                    暂无通知
                  </div>
                  <div v-for="n in notifications" :key="String(n.id)" class="notify-item" :class="{ unread: !n.is_read }" @click="markRead(n)">
                    <div class="notify-title">
                      <a-tag :color="n.ntype === 'doc_failed' ? 'error' : n.ntype === 'doc_indexed' ? 'success' : 'blue'" size="small" style="margin-right: 6px">
                        {{ n.ntype === 'doc_failed' ? '失败' : n.ntype === 'doc_indexed' ? '完成' : '系统' }}
                      </a-tag>
                      {{ String(n.title) }}
                    </div>
                    <div v-if="n.content" class="notify-content">{{ String(n.content) }}</div>
                    <div class="notify-time">{{ fmtTime(String(n.created_at)) }}</div>
                  </div>
                </div>
              </template>
            </a-dropdown>
          </a-badge>
          <a-dropdown>
            <div class="user-chip">
              <a-avatar size="small" style="background: #1668dc"><UserOutlined /></a-avatar>
              <span class="user-name">{{ auth.displayName || '...' }}</span>
            </div>
          <template #overlay>
            <a-menu>
              <a-menu-item disabled>{{ roleText }}</a-menu-item>
              <a-menu-divider />
              <a-menu-item key="logout" @click="onLogout"><LogoutOutlined /> 退出登录</a-menu-item>
            </a-menu>
          </template>
          </a-dropdown>
        </a-space>
      </a-layout-header>
      <a-layout-content class="app-content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { computed, h, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BellOutlined,
  BulbOutlined,
  CommentOutlined,
  DatabaseOutlined,
  LogoutOutlined,
  RobotOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'
import { api } from '../api'
import { fmtTime } from '../utils/time'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const isDark = inject<{ value: boolean }>('isDark', { value: false })
const toggleDark = inject<() => void>('toggleDark', () => {})
const notifications = ref<Record<string, unknown>[]>([])
const unreadCount = ref(0)
let notifyTimer: ReturnType<typeof setInterval> | null = null

async function loadNotifications() {
  try {
    const [list, cnt] = await Promise.all([
      api.get('/notifications', { params: { limit: 30 } }),
      api.get('/notifications/unread-count'),
    ])
    notifications.value = list.data as Record<string, unknown>[]
    unreadCount.value = (cnt.data as { count: number }).count
  } catch {
    /* ignore */
  }
}

async function markRead(n: Record<string, unknown>) {
  if (n.is_read) return
  await api.post(`/notifications/${String(n.id)}/read`)
  loadNotifications()
}

async function markAllRead() {
  await api.post('/notifications/read-all')
  loadNotifications()
}

const menuItems = computed(() => {
  const items = [
    { key: '/chat', icon: h(CommentOutlined), label: '智能问答' },
    { key: '/kbs', icon: h(DatabaseOutlined), label: '知识库管理' },
  ]
  if (auth.user?.role === 'admin') {
    items.push({ key: '/admin', icon: h(SettingOutlined), label: '系统管理' })
  }
  return items
})

const selectedKey = computed(() => {
  const p = route.path
  if (p.startsWith('/kbs')) return '/kbs'
  if (p.startsWith('/admin')) return '/admin'
  return '/chat'
})

const roleText = computed(() => {
  const r = auth.user?.role
  return r === 'admin' ? '角色：管理员' : r === 'editor' ? '角色：编辑' : '角色：只读'
})

onMounted(() => {
  if (!auth.user) auth.fetchMe().catch(() => {})
  loadNotifications()
  notifyTimer = setInterval(loadNotifications, 30000)
})
onBeforeUnmount(() => {
  if (notifyTimer) clearInterval(notifyTimer)
})

function onMenuClick(e: { key: string }) {
  router.push(e.key)
}

function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
  /* 兜底：任何情况下外层不产生页面滚动 */
  overflow: hidden;
}
/* antdv 嵌套 Layout 的中间层需要可收缩，否则内容超高会撑破 100vh */
.app-layout :deep(.ant-layout) {
  min-height: 0;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  font-size: 17px;
  font-weight: 600;
}
.brand-icon {
  color: #4e9bff;
}
.app-header {
  background: #fff;
  padding: 0 24px;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  height: 56px;
  line-height: 56px;
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.user-name {
  font-weight: 600;
}
.notify-panel {
  width: 340px;
  max-height: 420px;
  overflow: auto;
  background: #fff;
  border-radius: 8px;
}
.notify-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  font-weight: 600;
  border-bottom: 1px solid #f0f0f0;
}
.notify-item {
  padding: 8px 12px;
  border-bottom: 1px solid #f5f5f5;
  cursor: pointer;
}
.notify-item:hover {
  background: #fafafa;
}
.notify-item.unread {
  background: #f0f7ff;
}
.notify-title {
  font-size: 13px;
  font-weight: 500;
}
.notify-content {
  font-size: 12px;
  color: #888;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notify-time {
  font-size: 11px;
  color: #bbb;
  margin-top: 2px;
}
html[data-theme='dark'] .notify-panel {
  background: #1d1d24;
}
html[data-theme='dark'] .notify-item:hover {
  background: #26262e;
}
html[data-theme='dark'] .notify-item.unread {
  background: #16233b;
}
.app-content {
  /* flex 列布局：子页面可用 flex:1 + min-height:0 精确填满剩余空间，
     使聊天页等全屏交互页面内部滚动，页面本身永不出现滚动条 */
  display: flex;
  flex-direction: column;
  overflow: auto;
  padding: 20px;
  min-height: 0;
}
.app-content > * {
  min-height: 0;
}
</style>