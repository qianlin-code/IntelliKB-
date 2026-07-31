<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/store/user'
import { registerApi } from '@/api/auth'

// N18: 纯 UI 组件 — emits submit
const emit = defineEmits<{ submit: [username: string, password: string] }>()

const router = useRouter()
const userStore = useUserStore()
const activeTab = ref('login')

// 登录表单
const loginFormRef = ref<FormInstance>()
const loginLoading = ref(false)
const loginForm = reactive({ username: '', password: '' })
const loginRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, message: '用户名至少3个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6个字符', trigger: 'blur' },
  ],
}

async function handleLogin() {
  if (!loginFormRef.value) return
  const valid = await loginFormRef.value.validate().catch(() => false)
  if (!valid) return
  loginLoading.value = true
  try {
    emit('submit', loginForm.username, loginForm.password)
    await userStore.login(loginForm.username, loginForm.password)
    ElMessage.success('登录成功')
    router.push('/dashboard')
  } catch (error: any) {
    const msg = error?.response?.data?.message || error?.response?.data?.detail
    if (error?.response?.status === 401) {
      ElMessage.error(msg || '用户名或密码错误')
    } else if (error?.response?.status === 429) {
      ElMessage.error(msg || '请求过于频繁，请稍后重试')
    } else {
      ElMessage.error(msg || '登录失败，请稍后重试')
    }
    loginForm.password = ''
  } finally {
    loginLoading.value = false
  }
}

// 注册表单
const regFormRef = ref<FormInstance>()
const regLoading = ref(false)
const regForm = reactive({
  username: '', password: '', confirm_password: '', email: '',
})
const validateRegConfirm = (_rule: any, value: string, cb: any) => {
  if (value !== regForm.password) cb(new Error('两次密码不一致'))
  else cb()
}
const regRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, message: '用户名至少3个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6个字符', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateRegConfirm, trigger: 'blur' },
  ],
}

async function handleRegister() {
  if (!regFormRef.value) return
  const valid = await regFormRef.value.validate().catch(() => false)
  if (!valid) return
  regLoading.value = true
  try {
    await registerApi({
      username: regForm.username,
      password: regForm.password,
      email: regForm.email || undefined,
    })
    ElMessage.success('注册成功，请登录')
    regForm.username = ''; regForm.password = ''; regForm.confirm_password = ''; regForm.email = ''
    activeTab.value = 'login'
  } catch (error: any) {
    const msg = error?.response?.data?.message || error?.response?.data?.detail
    if (error?.response?.status === 429) {
      ElMessage.error(msg || '注册次数过多，请稍后重试')
    } else {
      ElMessage.error(msg || '注册失败，请稍后重试')
    }
  } finally {
    regLoading.value = false
  }
}
</script>

<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-left">
        <h1>IntelliKB</h1>
        <p>AI 智能知识库平台</p>
      </div>
      <el-divider direction="vertical" style="height: 380px" />
      <div class="login-right">
        <el-tabs v-model="activeTab" class="auth-tabs">
          <el-tab-pane label="用户登录" name="login">
            <el-form
              ref="loginFormRef"
              :model="loginForm"
              :rules="loginRules"
              label-width="0"
              size="large"
              @keyup.enter="handleLogin"
            >
              <el-form-item prop="username">
                <el-input v-model="loginForm.username" placeholder="用户名" prefix-icon="User" />
              </el-form-item>
              <el-form-item prop="password">
                <el-input v-model="loginForm.password" type="password" placeholder="密码" show-password prefix-icon="Lock" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="loginLoading" style="width: 100%" @click="handleLogin">
                  登 录
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="用户注册" name="register">
            <el-form ref="regFormRef" :model="regForm" :rules="regRules" label-width="0" size="large">
              <el-form-item prop="username">
                <el-input v-model="regForm.username" placeholder="用户名" prefix-icon="User" />
              </el-form-item>
              <el-form-item prop="password">
                <el-input v-model="regForm.password" type="password" placeholder="密码" show-password prefix-icon="Lock" />
              </el-form-item>
              <el-form-item prop="confirm_password">
                <el-input v-model="regForm.confirm_password" type="password" placeholder="确认密码" show-password prefix-icon="Lock" />
              </el-form-item>
              <el-form-item prop="email">
                <el-input v-model="regForm.email" placeholder="邮箱（选填）" />
              </el-form-item>
              <el-form-item>
                <el-button type="success" :loading="regLoading" style="width: 100%" @click="handleRegister">
                  注 册
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  display: flex;
  align-items: center;
  background: #fff;
  border-radius: 12px;
  padding: 40px 48px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.12);
}
.login-left {
  text-align: center;
  padding-right: 40px;
}
.login-left h1 {
  font-size: 32px;
  color: #303133;
  margin-bottom: 8px;
}
.login-left p {
  font-size: 14px;
  color: #909399;
}
.login-right {
  padding-left: 40px;
  width: 360px;
}
.auth-tabs {
  width: 100%;
}
</style>
