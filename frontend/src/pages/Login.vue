<template>
  <div class="login-wrap">
    <a-card class="login-card">
      <div class="login-head">
        <RobotOutlined class="login-logo" />
        <h2 class="login-title">KnowHub 知枢</h2>
        <p class="login-sub">企业级 RAG 知识库 Agent</p>
      </div>
      <a-form :model="form" layout="vertical" @finish="onFinish">
        <a-form-item name="username" :rules="[{ required: true, message: '请输入用户名' }]">
          <a-input v-model:value="form.username" size="large" placeholder="用户名" autocomplete="username">
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item name="password" :rules="[{ required: true, message: '请输入密码' }]">
          <a-input-password v-model:value="form.password" size="large" placeholder="密码" autocomplete="current-password">
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>
        <a-button type="primary" html-type="submit" size="large" block :loading="loading">
          登 录
        </a-button>
      </a-form>
      <div class="login-foot">
        <a @click="regOpen = true">注册账号</a>
        <span class="login-tip">管理员：admin / admin123456</span>
      </div>
    </a-card>

    <a-modal
      title="注册账号"
      v-model:open="regOpen"
      :confirm-loading="regLoading"
      @ok="onRegister"
      destroy-on-close
    >
      <a-alert
        style="margin-bottom: 16px"
        type="info"
        show-icon
        message="注册后默认为「只读」角色，可立即使用智能问答；如需上传文档等管理权限，请联系超级管理员在「系统管理 → 用户管理」中调整。"
      />
      <a-form ref="regFormRef" :model="regForm" :label-col="{ span: 5 }">
        <a-form-item label="用户名" name="username" :rules="regRules.username">
          <a-input v-model:value="regForm.username" placeholder="2-64 位字母、数字、_-. " />
        </a-form-item>
        <a-form-item label="密码" name="password" :rules="regRules.password">
          <a-input-password v-model:value="regForm.password" placeholder="至少 6 位" />
        </a-form-item>
        <a-form-item label="确认密码" name="confirm" :rules="regRules.confirm">
          <a-input-password v-model:value="regForm.confirm" placeholder="再次输入密码" />
        </a-form-item>
        <a-form-item label="姓名" name="display_name">
          <a-input v-model:value="regForm.display_name" placeholder="选填" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { LockOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const regOpen = ref(false)
const regLoading = ref(false)
const regFormRef = ref()
const regForm = reactive({ username: '', password: '', confirm: '', display_name: '' })
const regRules = {
  username: [
    { required: true, message: '请输入用户名' },
    { pattern: /^[a-zA-Z0-9_.-]{2,64}$/, message: '2-64 位字母、数字、_-. ' },
  ],
  password: [
    { required: true, message: '请输入密码' },
    { min: 6, message: '密码至少 6 位' },
  ],
  confirm: [
    { required: true, message: '请再次输入密码' },
    {
      validator: (_: unknown, v: string) =>
        v === regForm.password ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致')),
    },
  ],
}

async function onFinish() {
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    message.success(`欢迎回来，${auth.displayName || form.username}`)
    router.push('/chat')
  } catch (e) {
    message.error(auth.errorText(e))
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  try {
    await regFormRef.value.validateFields()
  } catch {
    return
  }
  regLoading.value = true
  try {
    await auth.register(regForm.username, regForm.password, regForm.display_name)
    message.success('注册成功，已自动登录（只读角色）')
    regOpen.value = false
    router.push('/chat')
  } catch (e) {
    message.error(auth.errorText(e))
  } finally {
    regLoading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f2b52 0%, #1668dc 100%);
}
.login-card {
  width: 400px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}
.login-head {
  text-align: center;
  margin-bottom: 24px;
}
.login-logo {
  font-size: 44px;
  color: #1668dc;
}
.login-title {
  margin: 12px 0 4px;
}
.login-sub {
  color: #8c8c8c;
  margin: 0;
}
.login-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
}
.login-tip {
  color: #bfbfbf;
  font-size: 12px;
}
</style>