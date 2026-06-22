<template>
  <main class="admin-page">
    <header>
      <div>
        <p>权限与账户</p>
        <h1>用户管理</h1>
      </div>
      <button class="primary" type="button" @click="openCreate">新增用户</button>
    </header>

    <section class="user-section">
      <div class="section-heading">
        <h2>系统账户</h2>
        <span>共 {{ users.length }} 个账户</span>
      </div>

      <p v-if="error" class="notice error">{{ error }}</p>
      <p v-if="message" class="notice success">{{ message }}</p>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户名</th>
              <th>姓名</th>
              <th>角色</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in users" :key="item.username">
              <td class="username">{{ item.username }}</td>
              <td>{{ item.displayName || '-' }}</td>
              <td>{{ roleLabel(item.role) }}</td>
              <td>
                <span :class="['status', item.enabled ? 'enabled' : 'disabled']">
                  {{ item.enabled ? '启用' : '停用' }}
                </span>
              </td>
              <td>{{ formatDate(item.createdAt) }}</td>
              <td>
                <template v-if="item.role !== 'admin'">
                  <button class="text-button" type="button" @click="openEdit(item)">编辑</button>
                  <button class="text-button danger" type="button" @click="remove(item)">删除</button>
                </template>
                <span v-else class="protected">系统账户</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="dialogOpen" class="dialog-backdrop" @click.self="closeDialog">
      <form class="user-dialog" @submit.prevent="save">
        <div class="dialog-title">
          <h2>{{ editing ? '编辑用户' : '新增用户' }}</h2>
          <button type="button" title="关闭" @click="closeDialog">×</button>
        </div>
        <label>
          <span>用户名</span>
          <input v-model.trim="form.username" :disabled="editing" required>
        </label>
        <label>
          <span>姓名</span>
          <input v-model.trim="form.display_name" placeholder="可选">
        </label>
        <label>
          <span>{{ editing ? '新密码（不修改请留空）' : '密码' }}</span>
          <input v-model="form.password" type="password" :required="!editing">
        </label>
        <label>
          <span>角色</span>
          <select v-model="form.role" required>
            <option value="operator">系统运行员</option>
            <option value="analyst">分析员</option>
          </select>
        </label>
        <label class="enabled-check">
          <input v-model="form.enabled" type="checkbox">
          <span>允许该账户登录</span>
        </label>
        <div class="dialog-actions">
          <button type="button" @click="closeDialog">取消</button>
          <button class="primary" type="submit" :disabled="saving">保存</button>
        </div>
      </form>
    </div>
  </main>
</template>

<script>
import api from '../services/api'

const emptyForm = () => ({
  username: '',
  display_name: '',
  password: '',
  role: 'operator',
  enabled: true,
})

export default {
  name: 'AdminUsers',
  props: {
    currentUser: {
      type: Object,
      required: true,
    },
  },
  data() {
    return {
      users: [],
      form: emptyForm(),
      editing: false,
      dialogOpen: false,
      saving: false,
      error: '',
      message: '',
    }
  },
  created() {
    this.loadUsers()
  },
  methods: {
    async loadUsers() {
      try {
        this.users = await api.listUsers()
      } catch (error) {
        this.error = error.message
      }
    },
    roleLabel(role) {
      return {
        admin: '超级管理员',
        operator: '系统运行员',
        analyst: '分析员',
      }[role] || role
    },
    formatDate(value) {
      return value ? new Date(value).toLocaleString('zh-CN') : '-'
    },
    openCreate() {
      this.form = emptyForm()
      this.editing = false
      this.dialogOpen = true
    },
    openEdit(item) {
      this.form = {
        username: item.username,
        display_name: item.displayName || '',
        password: '',
        role: item.role,
        enabled: item.enabled,
      }
      this.editing = true
      this.dialogOpen = true
    },
    closeDialog() {
      this.dialogOpen = false
    },
    async save() {
      this.saving = true
      this.error = ''
      try {
        const payload = {
          username: this.form.username,
          displayName: this.form.display_name,
          password: this.form.password,
          role: this.form.role,
          enabled: this.form.enabled,
        }
        if (!payload.password) delete payload.password
        if (this.editing) {
          await api.updateUser(this.form.username, payload)
          this.message = '用户信息已更新'
        } else {
          await api.createUser(payload)
          this.message = '用户已创建'
        }
        this.closeDialog()
        await this.loadUsers()
      } catch (error) {
        this.error = error.message
      } finally {
        this.saving = false
      }
    },
    async remove(item) {
      if (!window.confirm(`确定删除用户“${item.username}”吗？`)) return
      this.error = ''
      try {
        await api.deleteUser(item.username)
        this.message = '用户已删除'
        await this.loadUsers()
      } catch (error) {
        this.error = error.message
      }
    },
  },
}
</script>

<style scoped>
.admin-page {
  min-height: 100%;
  padding: 44px clamp(24px, 6vw, 90px) 90px;
  background: #f2f5f4;
}

header {
  display: flex;
  max-width: 1180px;
  align-items: end;
  justify-content: space-between;
  margin: 0 auto 32px;
}

header p {
  margin: 0 0 4px;
  color: #187561;
  font-size: 14px;
  font-weight: 700;
}

h1 {
  margin: 0;
  font-size: 34px;
}

button {
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid #bdc7c5;
  border-radius: 5px;
  background: #fff;
  cursor: pointer;
}

button.primary {
  border-color: #176f5d;
  color: #fff;
  background: #176f5d;
}

.user-section {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
  border: 1px solid #d8dfdd;
  border-radius: 8px;
  background: #fff;
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 18px;
}

h2 {
  margin: 0;
  font-size: 20px;
}

.section-heading span {
  color: #76817f;
  font-size: 13px;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

th,
td {
  height: 52px;
  padding: 0 12px;
  border-bottom: 1px solid #e3e8e7;
  white-space: nowrap;
}

th {
  color: #67716f;
  background: #f6f8f7;
  font-size: 13px;
  font-weight: 600;
}

td {
  font-size: 14px;
}

.username {
  font-weight: 700;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.status::before {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  content: "";
}

.enabled {
  color: #14765f;
}

.disabled {
  color: #a44848;
}

.text-button {
  min-height: 30px;
  padding: 0 6px;
  border: 0;
  color: #176f5d;
}

.text-button.danger {
  color: #b23434;
}

.protected {
  color: #8b9492;
  font-size: 13px;
}

.notice {
  padding: 9px 12px;
  border-radius: 4px;
  font-size: 13px;
}

.notice.error {
  color: #932d2d;
  background: #fbeaea;
}

.notice.success {
  color: #17634f;
  background: #e7f5ef;
}

.dialog-backdrop {
  position: fixed;
  z-index: 10001;
  inset: 0;
  display: grid;
  padding: 20px;
  background: rgba(19, 25, 24, 0.48);
  place-items: center;
}

.user-dialog {
  width: min(440px, 100%);
  padding: 26px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
}

.dialog-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 22px;
}

.dialog-title button {
  width: 32px;
  min-height: 32px;
  padding: 0;
  border: 0;
  font-size: 24px;
}

label {
  display: block;
  margin-bottom: 15px;
}

label > span {
  display: block;
  margin-bottom: 6px;
  color: #52605d;
  font-size: 13px;
}

input,
select {
  width: 100%;
  height: 40px;
  padding: 0 10px;
  border: 1px solid #bcc7c5;
  border-radius: 4px;
  background: #fff;
}

.enabled-check {
  display: flex;
  align-items: center;
  gap: 8px;
}

.enabled-check input {
  width: 16px;
  height: 16px;
}

.enabled-check span {
  margin: 0;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 24px;
}

@media (max-width: 640px) {
  header {
    align-items: start;
  }

  h1 {
    font-size: 28px;
  }

  .user-section {
    padding: 14px;
  }
}
</style>
