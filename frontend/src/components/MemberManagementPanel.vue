<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  createMember,
  disableMember,
  listMembers,
  resetMemberPassword,
  updateMember,
  type WorkspaceMember,
} from '../api'
import { localizedSystemText } from '../localization'

const props = defineProps<{
  open: boolean
  currentUserId: string
}>()
const emit = defineEmits<{
  currentUserChanged: []
}>()

const members = ref<WorkspaceMember[]>([])
const loading = ref(false)
const saving = ref('')
const error = ref('')
const notice = ref('')
const username = ref('')
const displayName = ref('')
const role = ref<WorkspaceMember['role']>('viewer')
const temporaryPassword = ref('')
const resetTarget = ref('')
const resetPassword = ref('')

const activeAdmins = computed(() => members.value.filter(
  member => member.is_active && member.role === 'admin',
).length)
const canCreate = computed(() => Boolean(
  username.value.trim().length >= 3 && temporaryPassword.value.length >= 12 && !saving.value,
))

function readableError(caught: unknown, fallback: string) {
  return localizedSystemText(caught instanceof Error ? caught.message : '', fallback)
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    members.value = await listMembers()
  } catch (caught) {
    error.value = readableError(caught, '成员列表加载失败。')
  } finally {
    loading.value = false
  }
}

async function submitMember() {
  if (!canCreate.value) return
  saving.value = 'create'
  error.value = ''
  notice.value = ''
  const password = temporaryPassword.value
  temporaryPassword.value = ''
  try {
    const member = await createMember({
      username: username.value.trim(),
      display_name: displayName.value.trim(),
      role: role.value as 'admin' | 'editor' | 'viewer',
      temporary_password: password,
    })
    members.value = [...members.value, member]
    username.value = ''
    displayName.value = ''
    role.value = 'viewer'
    notice.value = `已创建 ${member.username}，对方首次登录后必须修改临时密码。`
  } catch (caught) {
    error.value = readableError(caught, '成员创建失败。')
  } finally {
    saving.value = ''
  }
}

async function changeRole(member: WorkspaceMember, nextRole: WorkspaceMember['role']) {
  if (nextRole === member.role) return
  saving.value = member.user_id
  error.value = ''
  try {
    const updated = await updateMember(member.user_id, { role: nextRole as 'admin' | 'editor' | 'viewer' })
    replace(updated)
    notice.value = `${updated.username} 的角色已更新。其现有会话已撤销。`
    if (updated.user_id === props.currentUserId) emit('currentUserChanged')
  } catch (caught) {
    error.value = readableError(caught, '角色更新失败。')
  } finally {
    saving.value = ''
  }
}

async function toggleMember(member: WorkspaceMember) {
  saving.value = member.user_id
  error.value = ''
  try {
    const updated = member.is_active
      ? await disableMember(member.user_id)
      : await updateMember(member.user_id, { is_active: true })
    replace(updated)
    notice.value = `${updated.username} 已${updated.is_active ? '启用' : '禁用'}。`
  } catch (caught) {
    error.value = readableError(caught, '成员状态更新失败。')
  } finally {
    saving.value = ''
  }
}

async function submitReset(member: WorkspaceMember) {
  if (resetPassword.value.length < 12) return
  saving.value = member.user_id
  error.value = ''
  const password = resetPassword.value
  resetPassword.value = ''
  try {
    const updated = await resetMemberPassword(member.user_id, password)
    replace(updated)
    resetTarget.value = ''
    notice.value = `${updated.username} 的密码已重置，全部会话已撤销。`
    if (updated.user_id === props.currentUserId) emit('currentUserChanged')
  } catch (caught) {
    error.value = readableError(caught, '密码重置失败。')
  } finally {
    saving.value = ''
  }
}

function replace(updated: WorkspaceMember) {
  members.value = members.value.map(member => member.user_id === updated.user_id ? updated : member)
}

watch(() => props.open, open => {
  if (open) void refresh()
  else {
    temporaryPassword.value = ''
    resetPassword.value = ''
    resetTarget.value = ''
  }
}, { immediate: true })
</script>

<template>
  <div class="member-management-panel" :aria-busy="loading">
    <section class="member-summary" aria-label="成员概况">
      <div><span>成员</span><strong>{{ members.length }}</strong></div>
      <div><span>启用中</span><strong>{{ members.filter(member => member.is_active).length }}</strong></div>
      <div><span>管理员</span><strong>{{ activeAdmins }}</strong></div>
    </section>

    <p v-if="error" class="model-connection-message error" role="alert">{{ error }}</p>
    <p v-else-if="notice" class="model-connection-message" role="status">{{ notice }}</p>

    <section class="member-create" aria-labelledby="member-create-title">
      <div class="member-section-heading">
        <div><span>无公开注册</span><h3 id="member-create-title">创建内部成员</h3></div>
      </div>
      <form class="member-form" @submit.prevent="submitMember">
        <label>用户名<input v-model="username" name="new-member-username" autocomplete="off" minlength="3" maxlength="64" required></label>
        <label>显示名<input v-model="displayName" name="new-member-display-name" autocomplete="off" maxlength="128"></label>
        <label>角色
          <select v-model="role" name="new-member-role">
            <option value="viewer">查看者</option><option value="editor">编辑者</option><option value="admin">管理员</option>
          </select>
        </label>
        <label>临时密码<input v-model="temporaryPassword" name="temporary-password" type="password" autocomplete="new-password" minlength="12" required></label>
        <small>至少 12 个字符；创建后请通过安全渠道交给成员。</small>
        <button class="button primary" type="submit" :disabled="!canCreate">创建成员</button>
      </form>
    </section>

    <section class="member-list" aria-labelledby="member-list-title">
      <div class="member-section-heading">
        <div><span>立即撤销会话</span><h3 id="member-list-title">已有成员</h3></div>
        <button class="button secondary" type="button" :disabled="loading" @click="refresh">刷新</button>
      </div>
      <p v-if="loading && !members.length" role="status">正在加载成员…</p>
      <article v-for="member in members" :key="member.user_id" class="member-card" :class="{ disabled: !member.is_active }">
        <header><div><strong>{{ member.display_name || member.username }}</strong><span>@{{ member.username }}</span></div><em>{{ member.is_active ? '已启用' : '已禁用' }}</em></header>
        <div class="member-controls">
          <label>角色
            <select :value="member.role" :disabled="saving === member.user_id" @change="changeRole(member, ($event.target as HTMLSelectElement).value as WorkspaceMember['role'])">
              <option value="viewer">查看者</option><option value="editor">编辑者</option><option value="admin">管理员</option>
            </select>
          </label>
          <span v-if="member.must_change_password" class="member-badge">待修改密码</span>
        </div>
        <div class="member-actions">
          <button class="button secondary" type="button" :disabled="saving === member.user_id || (member.user_id === currentUserId && member.is_active)" @click="toggleMember(member)">{{ member.is_active ? '禁用' : '重新启用' }}</button>
          <button class="button secondary" type="button" :disabled="saving === member.user_id" @click="resetTarget = resetTarget === member.user_id ? '' : member.user_id; resetPassword = ''">重置密码</button>
        </div>
        <form v-if="resetTarget === member.user_id" class="member-reset" @submit.prevent="submitReset(member)">
          <label>新临时密码<input v-model="resetPassword" type="password" autocomplete="new-password" minlength="12" required></label>
          <button class="button primary" type="submit" :disabled="resetPassword.length < 12 || saving === member.user_id">确认重置</button>
        </form>
      </article>
    </section>
  </div>
</template>

<style scoped>
.member-management-panel { display: grid; gap: 1.25rem; padding: 0 1.25rem 2rem; overflow: auto; }
.member-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; }
.member-summary div { border: 1px solid var(--line-soft); padding: .8rem; display: grid; gap: .25rem; }
.member-summary span, .member-section-heading span, .member-card header span, .member-form small { color: var(--text-muted); font-size: .75rem; }
.member-summary strong { font-size: 1.4rem; }
.member-create, .member-list { display: grid; gap: .9rem; }
.member-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.member-section-heading h3 { margin: .15rem 0 0; }
.member-form, .member-reset { display: grid; gap: .7rem; }
.member-form label, .member-reset label, .member-controls label { display: grid; gap: .3rem; font-size: .78rem; font-weight: 700; }
.member-form input, .member-form select, .member-reset input, .member-controls select { width: 100%; min-height: 2.55rem; border: 1px solid var(--line-soft); background: var(--surface); color: inherit; padding: .55rem .65rem; }
.member-card { border-top: 1px solid var(--line-soft); padding-top: .9rem; display: grid; gap: .75rem; }
.member-card.disabled { opacity: .65; }
.member-card header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.member-card header div { display: grid; gap: .15rem; }
.member-card header em { font-size: .7rem; font-style: normal; text-transform: uppercase; }
.member-controls, .member-actions { display: flex; align-items: end; gap: .6rem; flex-wrap: wrap; }
.member-controls label { flex: 1 1 9rem; }
.member-badge { border: 1px solid var(--line-soft); padding: .42rem .55rem; font-size: .7rem; }
@media (max-width: 560px) { .member-summary { grid-template-columns: 1fr; } }
</style>
