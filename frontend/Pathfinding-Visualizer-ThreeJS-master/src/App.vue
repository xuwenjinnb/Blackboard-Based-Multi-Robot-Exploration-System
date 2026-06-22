<template>
  <div id="app">
    <div v-if="loading" class="loading-screen">正在验证登录状态...</div>

    <LoginView
      v-else-if="!user"
      @logged-in="handleLoggedIn"
    />

    <template v-else>
      <AdminUsers v-if="user.role === 'admin'" :current-user="user" />
      <PathfindingVisualizer v-else-if="user.role === 'operator'" />
      <ReplayViewer v-else :current-user="user" />

      <div class="session-strip">
        <span>{{ user.username }}</span>
        <span class="role-label">{{ roleName }}</span>
        <button type="button" title="退出登录" @click="handleLogout">退出</button>
      </div>
    </template>
  </div>
</template>

<script>
import api, { getToken } from './services/api'
import LoginView from './components/LoginView.vue'
import AdminUsers from './components/AdminUsers.vue'
import PathfindingVisualizer from './components/PathfindingVisualizer.vue'
import ReplayViewer from './components/ReplayViewer.vue'

export default {
  name: 'App',
  components: {
    LoginView,
    AdminUsers,
    PathfindingVisualizer,
    ReplayViewer,
  },
  data() {
    return {
      loading: Boolean(getToken()),
      user: null,
    }
  },
  computed: {
    roleName() {
      return {
        admin: '超级管理员',
        operator: '系统运行员',
        analyst: '分析员',
      }[this.user && this.user.role] || ''
    },
  },
  async created() {
    if (!getToken()) {
      this.loading = false
      return
    }
    try {
      this.user = await api.currentUser()
    } catch (error) {
      api.clearToken()
    } finally {
      this.loading = false
    }
  },
  methods: {
    handleLoggedIn(user) {
      this.user = user
    },
    async handleLogout() {
      try {
        await api.logout()
      } finally {
        this.user = null
      }
    },
  },
}
</script>

<style>
html,
body,
#app {
  width: 100%;
  height: 100%;
  margin: 0;
}

* {
  box-sizing: border-box;
}

body {
  color: #202428;
  background: #f4f6f7;
  font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
}

button,
input,
select {
  font: inherit;
}

.loading-screen {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  color: #52606a;
}

.session-strip {
  position: fixed;
  z-index: 10000;
  right: 16px;
  bottom: 14px;
  display: flex;
  min-height: 34px;
  align-items: center;
  gap: 9px;
  padding: 5px 6px 5px 12px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 6px;
  color: #fff;
  background: rgba(25, 31, 35, 0.9);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  font-size: 13px;
}

.session-strip .role-label {
  color: #a8d8ca;
}

.session-strip button {
  height: 26px;
  padding: 0 9px;
  border: 0;
  border-radius: 4px;
  color: #fff;
  background: #b83b3b;
  cursor: pointer;
}
</style>
