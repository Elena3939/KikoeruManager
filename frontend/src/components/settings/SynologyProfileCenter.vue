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
      <SettingsFieldCard label="连接 ID">
        <input v-model="profile.id" class="profile-input" type="text" placeholder="例如 synology-main">
      </SettingsFieldCard>
      <SettingsFieldCard label="连接名称">
        <input v-model="profile.name" class="profile-input" type="text" placeholder="例如 主群晖连接">
      </SettingsFieldCard>
    </div>

    <div class="field-grid two">
      <SettingsFieldCard label="群晖地址">
        <input v-model="profile.base_url" class="profile-input" type="text" placeholder="https://nas.example.com:5001">
      </SettingsFieldCard>
      <SettingsFieldCard label="会话名">
        <input v-model="profile.session_name" class="profile-input" type="text" placeholder="FileStation">
      </SettingsFieldCard>
    </div>

    <div class="field-grid three">
      <SettingsFieldCard label="用户名">
        <input v-model="profile.username" class="profile-input" type="text" placeholder="DSM 用户名">
      </SettingsFieldCard>
      <SettingsFieldCard label="密码">
        <AnimatedPasswordInput v-model="profile.password" placeholder="DSM 密码" autocomplete="current-password" />
      </SettingsFieldCard>
      <SettingsFieldCard label="OTP 动态码" hint="有 `device_id` 后通常不需要反复输入。">
        <input v-model="profile.otp_code" class="profile-input" type="text" placeholder="首次验证或重新验证时填写">
      </SettingsFieldCard>
    </div>

    <div class="field-grid three">
      <SettingsFieldCard label="设备名称">
        <input v-model="profile.device_name" class="profile-input" type="text" placeholder="例如 KikoeruManager">
      </SettingsFieldCard>
      <SettingsFieldCard label="设备令牌 ID">
        <input v-model="profile.device_id" class="profile-input" type="text" placeholder="测试成功后自动回填">
      </SettingsFieldCard>
      <SettingsFieldCard label="超时（秒）">
        <SettingsNumberStepper v-model="profile.timeout" :min="5" :step="5" />
      </SettingsFieldCard>
    </div>

    <div class="toggle-row">
      <SettingsToggleRow
        :model-value="profile.enable_device_token"
        title="记住设备"
        subtitle="保存设备令牌，减少重复 OTP 验证。"
      >
        <template #control>
          <AppLottieTextButton
            :src="rememberDeviceAnimation"
            :label="profile.enable_device_token ? '已记住' : '记住设备'"
            :active="profile.enable_device_token"
            compact
            @click="emitProfileFlag('enable_device_token', !profile.enable_device_token)"
          />
        </template>
      </SettingsToggleRow>
      <SettingsToggleRow
        :model-value="profile.verify_ssl"
        title="校验证书"
        subtitle="自签名证书可先关闭，正式环境建议开启。"
        @update:model-value="emitProfileFlag('verify_ssl', $event)"
      />
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
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
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
/* Flat 风：去所有独立字段卡/toggle卡，只靠 grid gap 与 space 划分字段与分组 */
.single-profile-shell {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.profile-banner {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 0;
  background: transparent;
  border: none;
  box-shadow: none;
}

.profile-title {
  color: var(--set-text-strong);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.profile-desc {
  margin-top: 4px;
  color: var(--set-text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.profile-status-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-content: flex-start;
  justify-content: flex-end;
  flex-shrink: 0;
}

/* 顶部状态标签：低饱和语义色，平面细边 */
.status-chip {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--set-border);
  background: var(--set-tag-info-bg);
  color: var(--set-tag-info-text);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0;
  box-shadow: none;
}

.status-chip.is-good {
  background: var(--set-success-bg);
  color: var(--set-success-text);
  border-color: var(--set-success-border);
  box-shadow: none;
}

.status-chip.is-warn {
  background: var(--set-warning-bg);
  color: var(--set-warning-text);
  border-color: var(--set-warning-border);
  box-shadow: none;
}

/* 字段网格：平铺二列 / 三列，SettingsFieldCard 负责控件槽、label、hint排版 */
.field-grid {
  display: grid;
  gap: 14px 18px;
  align-items: start;
}

.field-grid.two   { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }

/* SettingsFieldCard 默认 slot 里裸 input 的统一外观 */
.profile-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--set-border);
  outline: none;
  border-radius: 10px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  font-size: 13.5px;
  box-shadow: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.profile-input:hover { border-color: var(--set-border-strong); }

.profile-input:focus {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.profile-input::placeholder { color: var(--set-text-subtle); }

/* toggle 行外层 grid：SettingsToggleRow 负责行内颜值，外层只负责二列排列 */
.toggle-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
  align-items: start;
}

.actions-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

/* 主按钮：中性实体按钮，去掉胶质高光 */
.primary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  padding: 0 18px;
  border-radius: 10px;
  border: 1px solid var(--set-primary-border);
  color: var(--set-primary-text);
  background: var(--set-primary-bg);
  box-shadow: none;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.primary-btn:not(:disabled):hover {
  transform: translateY(-2px);
  background: var(--set-primary-bg-hover);
  box-shadow: 0 8px 18px -14px rgba(0, 0, 0, 0.55);
}

.primary-btn:not(:disabled):active {
  transform: translateY(0) scale(0.97);
}

.primary-btn:disabled { opacity: 0.55; cursor: not-allowed; }

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .profile-banner { flex-direction: column; }
  .field-grid.two,
  .field-grid.three,
  .toggle-row { grid-template-columns: 1fr; }
}

/* 仅保留 lottie 控件贴 SettingsToggleRow 右侧时必要的 z-index，避免 hover 被遮挡 */
:deep(.str-control) {
  position: relative;
  z-index: 2;
}
</style>
