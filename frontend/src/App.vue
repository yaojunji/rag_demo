<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <router-view />
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { theme as antTheme } from 'ant-design-vue'

const dark = ref(localStorage.getItem('knowhub_dark') === '1')

const themeConfig = computed(() => ({
  token: { colorPrimary: '#1668dc', borderRadius: 8 },
  algorithm: dark.value ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
}))

// 同步根元素 data-theme（供全局 CSS 变量切换）
watch(
  dark,
  (v) => {
    document.documentElement.dataset.theme = v ? 'dark' : 'light'
  },
  { immediate: true }
)

function toggleDark() {
  dark.value = !dark.value
  localStorage.setItem('knowhub_dark', dark.value ? '1' : '0')
}

provide('toggleDark', toggleDark)
provide('isDark', dark)
</script>
