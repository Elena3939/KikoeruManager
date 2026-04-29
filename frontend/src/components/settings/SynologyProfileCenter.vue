<template>
  <div class="single-profile-shell">
    <div class="profile-banner">
      <div>
        <div class="profile-title">{{ profile.name || '主群晖连接' }}</div>
        <div class="profile-desc">所有远程共享目录统一复用这一套 NAS 连接，不再分别维护 IP、账号和 OTP。</div>
      </div>
      <div class="profile-status-strip">
        <span class="status-chip">{{ summary.linkedCount }} 个远程库存</span>
        <span class="status-chip" :class="summary.hasDeviceToken ? 'is-good' : 'is-warn'">
          {{ summary.hasDeviceToken ? '已记住设备' : '可能需要 OTP' }}
        </span>
      </div>
    </div>

    <div class="field-grid two">
      <label class="field-card">
        <span class="field-label">连接 ID</span>
        <input v-model="profile.id" class="field-input" type="text" placeholder="例如 synology-main">
      </label>
      <label class="field-card">
        <span class="field-label">连接名称</span>
        <input v-model="profile.name" class="field-input" type="text" placeholder="例如 主群晖连接">
      </label>
    </div>

    <div class="field-grid two">
      <label class="field-card">
        <span class="field-label">群晖地址</span>
        <input v-model="profile.base_url" class="field-input" type="text" placeholder="https://nas.example.com:5001">
      </label>
      <label class="field-card">
        <span class="field-label">会话名</span>
        <input v-model="profile.session_name" class="field-input" type="text" placeholder="FileStation">
      </label>
    </div>

    <div class="field-grid three">
      <label class="field-card">
        <span class="field-label">用户名</span>
        <input v-model="profile.username" class="field-input" type="text" placeholder="DSM 用户名">
      </label>
      <label class="field-card">
        <span class="field-label">密码</span>
        <AnimatedPasswordInput v-model="profile.password" placeholder="DSM 密码" autocomplete="current-password" />
      </label>
      <label class="field-card">
        <span class="field-label">OTP 动态码</span>
        <input v-model="profile.otp_code" class="field-input" type="text" placeholder="首次验证或重新验证时填写">
        <span class="field-tip">有 `device_id` 后通常不需要反复输入。</span>
      </label>
    </div>

    <div class="field-grid three">
      <label class="field-card">
        <span class="field-label">设备名称</span>
        <input v-model="profile.device_name" class="field-input" type="text" placeholder="例如 Prekikoeru">
      </label>
      <label class="field-card">
        <span class="field-label">设备令牌 ID</span>
        <input v-model="profile.device_id" class="field-input" type="text" placeholder="测试成功后自动回填">
      </label>
      <label class="field-card">
        <span class="field-label">超时（秒）</span>
        <el-input-number v-model="profile.timeout" :min="5" :step="5" class="field-number" />
      </label>
    </div>

    <div class="toggle-row">
      <div class="toggle-card" @click="emitProfileFlag('enable_device_token', !profile.enable_device_token)">
        <span>
          <strong>记住设备</strong>
          <small>保存设备令牌，减少重复 OTP 验证。</small>
        </span>
        <div class="toggle-control" @click.stop>
          <AppLottieTextButton
            :src="rememberDeviceAnimation"
            :label="profile.enable_device_token ? '已记住' : '记住设备'"
            :active="profile.enable_device_token"
            compact
            @click="emitProfileFlag('enable_device_token', !profile.enable_device_token)"
          />
        </div>
      </div>
      <div class="toggle-card" @click="emitProfileFlag('verify_ssl', !profile.verify_ssl)">
        <span>
          <strong>校验证书</strong>
          <small>自签名证书可先关闭，正式环境建议开启。</small>
        </span>
        <div class="toggle-control" @click.stop>
          <el-switch :model-value="profile.verify_ssl" @update:model-value="emitProfileFlag('verify_ssl', $event)" />
        </div>
      </div>
    </div>

    <div class="actions-row">
      <button
        type="button"
        class="primary-btn"
        :disabled="testingProfileId === profile.id"
        @click="$emit('test-profile', profile)"
      >
        <LoaderCircle v-if="testingProfileId === profile.id" :size="15" :stroke-width="2.5" class="spinning" />
        <PlugZap v-else :size="15" :stroke-width="2.5" />
        测试主连接
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { LoaderCircle, PlugZap } from 'lucide-vue-next'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import AppLottieTextButton from '../common/AppLottieTextButton.vue'
import rememberDeviceAnimation from '../../assets/anime/1111.lottie'

const props = defineProps({
  profile: { type: Object, required: true },
  profileSummary: { type: Object, default: () => ({}) },
  testingProfileId: { type: String, default: '' }
})

const emit = defineEmits(['test-profile', 'update-profile-flag'])

const summary = computed(() => ({
  linkedCount: props.profileSummary?.linkedCount || 0,
  hasDeviceToken: Boolean(props.profileSummary?.hasDeviceToken)
}))

function emitProfileFlag(key, value) {
  emit('update-profile-flag', { key, value })
}
</script>

<style scoped>
.single-profile-shell {
  display: grid;
  gap: 14px;
}

.profile-banner,
.field-card,
.toggle-card {
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.76);
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.profile-banner {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
}

.profile-title {
  color: #0f172a;
  font-size: 20px;
  font-weight: 800;
}

.profile-desc,
.field-tip,
.toggle-card small {
  margin-top: 8px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.65;
}

.profile-status-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-content: flex-start;
  justify-content: flex-end;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.92);
  color: #475569;
  font-size: 11px;
  font-weight: 800;
}

.status-chip.is-good {
  border-color: rgba(134, 239, 172, 0.95);
  color: #15803d;
  background: rgba(240, 253, 244, 0.96);
}

.status-chip.is-warn {
  border-color: rgba(253, 230, 138, 0.9);
  color: #b45309;
  background: rgba(255, 251, 235, 0.96);
}

.field-grid,
.toggle-row {
  display: flex;
  gap: 12px;
}

.field-grid.two > * {
  flex: 1;
}

.field-grid.three > * {
  flex: 1;
}

.field-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 14px;
}

.field-label {
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.field-input {
  width: 100%;
  min-height: 42px;
  padding: 0 12px;
  border: none;
  outline: none;
  border-radius: 12px;
  background: #ffffff;
  color: #0f172a;
  font-size: 14px;
  box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.84);
  transition: box-shadow 0.2s ease;
}

.field-input:focus {
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.72), 0 0 0 3px rgba(15, 23, 42, 0.06);
}

.field-number :deep(.el-input__wrapper) {
  min-height: 42px;
  border-radius: 12px;
}

.toggle-card {
  flex: 1;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 16px 18px;
}

.toggle-control {
  position: relative;
  z-index: 2;
  flex-shrink: 0;
  pointer-events: auto;
}

.toggle-control :deep(.el-switch) {
  pointer-events: auto;
}

.toggle-card strong {
  display: block;
  color: #0f172a;
  font-size: 14px;
}

.actions-row {
  display: flex;
  justify-content: flex-end;
}

.primary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 40px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid #0f172a;
  background: #0f172a;
  color: #f8fafc;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .profile-banner,
  .field-grid,
  .toggle-row {
    flex-direction: column;
  }
}
</style>
