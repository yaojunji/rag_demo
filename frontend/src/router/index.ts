import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../pages/Login.vue') },
    {
      path: '/',
      component: () => import('../pages/Layout.vue'),
      children: [
        { path: '', redirect: '/chat' },
        { path: 'chat', name: 'chat', component: () => import('../pages/ChatPage.vue') },
        { path: 'kbs', name: 'kbs', component: () => import('../pages/KBListPage.vue') },
        { path: 'kbs/:kbId', name: 'kb-docs', component: () => import('../pages/KBDocsPage.vue') },
        { path: 'admin', name: 'admin', component: () => import('../pages/AdminPage.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !getToken()) return '/login'
  if (to.path === '/login' && getToken()) return '/chat'
  return true
})

export default router