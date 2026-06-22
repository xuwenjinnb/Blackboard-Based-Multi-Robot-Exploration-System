<template>
  <main class="login-page">
    <section class="login-intro">
      <img src="../assets/logo.png" alt="" class="system-logo">
      <h1>多车协同探索系统</h1>
      <p>登录后将根据账户权限进入用户管理、仿真运行或数据回放界面。</p>
      <div class="role-lines" aria-label="系统角色">
        <span>超级管理员</span>
        <span>系统运行员</span>
        <span>分析员</span>
      </div>
    </section>

    <form class="login-form" @submit.prevent="submit">
      <h2>登录账户</h2>
      <label>
        <span>用户名</span>
        <input
          v-model.trim="username"
          name="username"
          autocomplete="username"
          autofocus
          required
        >
      </label>
      <label>
        <span>密码</span>
        <input
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
        >
      </label>
      <p v-if="error" class="login-error">{{ error }}</p>
      <button type="submit" :disabled="submitting">
        {{ submitting ? '正在登录...' : '登录' }}
      </button>
    </form>
  </main>
</template>

<script>
import api from '../services/api'

export default {
  name: 'LoginView',
  data() {
    return {
      username: '',
      password: '',
      submitting: false,
      error: '',
    }
  },
  methods: {
    async submit() {
      this.submitting = true
      this.error = ''
      try {
        const result = await api.login(this.username, this.password)
        this.$emit('logged-in', result.user)
      } catch (error) {
        this.error = error.message || '登录失败，请检查用户名和密码'
      } finally {
        this.submitting = false
      }
    },
  },
}
</script>

<style scoped>
.login-page {
  display: grid;
  min-height: 100%;
  grid-template-columns: minmax(360px, 1.15fr) minmax(340px, 0.85fr);
  color: #fff;
  background: #17282c;
}

.login-intro {
  display: flex;
  max-width: 760px;
  justify-content: center;
  flex-direction: column;
  padding: clamp(40px, 8vw, 120px);
}

.system-logo {
  width: 76px;
  height: 76px;
  margin-bottom: 22px;
  object-fit: contain;
}

h1 {
  max-width: 680px;
  margin: 0;
  font-size: clamp(42px, 6vw, 72px);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.2;
}

.login-intro > p {
  max-width: 560px;
  margin: 22px 0;
  color: #d9e3e4;
  font-size: 17px;
  line-height: 1.8;
}

.role-lines {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  color: #aebdbf;
  font-size: 14px;
}

.login-form {
  align-self: center;
  width: min(390px, calc(100% - 48px));
  justify-self: center;
  padding: 34px;
  border-radius: 8px;
  color: #20282b;
  background: #fff;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.28);
}

h2 {
  margin: 0 0 26px;
  font-size: 24px;
}

label {
  display: block;
  margin-bottom: 18px;
}

label span {
  display: block;
  margin-bottom: 7px;
  color: #465358;
  font-size: 14px;
}

input {
  width: 100%;
  height: 42px;
  padding: 0 11px;
  border: 1px solid #bcc8cb;
  border-radius: 5px;
  outline: none;
}

input:focus {
  border-color: #16836d;
  box-shadow: 0 0 0 3px rgba(22, 131, 109, 0.12);
}

.login-form button {
  width: 100%;
  height: 44px;
  margin-top: 5px;
  border: 0;
  border-radius: 5px;
  color: #fff;
  background: #147761;
  cursor: pointer;
  font-weight: 700;
}

.login-form button:disabled {
  cursor: wait;
  opacity: 0.65;
}

.login-error {
  margin: -5px 0 12px;
  color: #b42318;
  font-size: 13px;
}

@media (max-width: 760px) {
  .login-page {
    grid-template-columns: 1fr;
    align-content: center;
    gap: 20px;
    padding: 30px 0 60px;
  }

  .login-intro {
    align-items: center;
    padding: 24px;
    text-align: center;
  }

  .login-intro > p {
    margin: 12px auto;
  }

  .role-lines {
    justify-content: center;
  }

  h1 {
    font-size: 40px;
  }
}
</style>
