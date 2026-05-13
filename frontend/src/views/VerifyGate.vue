<template>
  <main class="gate-page relative min-h-screen flex items-center justify-center px-6 bg-white overflow-hidden">
    <section class="glass-card relative w-full max-w-[680px] rounded-[46px] px-10 sm:px-14 py-16 sm:py-20">
      <div class="relative z-10 w-full max-w-[520px] mx-auto">
        <header class="text-center mb-10">
          <div class="icon-glass mx-auto w-[70px] h-[70px] rounded-[24px] flex items-center justify-center mb-7">
            <ShieldCheck class="w-8 h-8 text-zinc-900" :stroke-width="2.2" />
          </div>

          <p class="text-sm tracking-wide text-zinc-500 font-medium mb-3">
            KikoeruManager 安全网关
          </p>

          <h1 class="text-[46px] sm:text-[52px] leading-none font-semibold tracking-tight text-zinc-950 mb-5">
            安全验证
          </h1>

          <p class="text-zinc-500 text-[16px] sm:text-[17px] leading-relaxed">
            使用 Google Authenticator 中的 6 位动态验证码进入系统。
          </p>
        </header>

      <div v-if="loading" class="gate-state">
        <Loader2 class="animate-spin" :size="18" />
        正在检查门禁状态
      </div>

      <template v-else-if="blocked">
        <div class="gate-alert is-danger">
          <Ban :size="18" />
          当前来源已被系统阻止。
        </div>
        <button type="button" class="gate-button is-muted" @click="goBlocked">
          查看阻止详情
          <ArrowRight :size="16" />
        </button>
      </template>

      <template v-else-if="!state.enabled">
        <div class="gate-alert is-soft">
          <UnlockKeyhole :size="18" />
          安全门禁尚未启用。
        </div>
        <button type="button" class="gate-button" @click="enterApp">
          进入系统
          <ArrowRight :size="16" />
        </button>
      </template>

      <template v-else-if="!state.bound">
        <div class="gate-alert is-soft">
          <QrCode :size="18" />
          首次启用前需要先绑定 Google Authenticator。
        </div>
        <div v-if="setup.qr_data_uri || setup.secret" class="setup-box">
          <img v-if="setup.qr_data_uri" :src="setup.qr_data_uri" alt="Google Authenticator 绑定二维码">
          <div class="setup-secret">
            <span>{{ setup.secret }}</span>
            <button type="button" @click="copySecret">
              <Copy :size="14" />
              复制密钥
            </button>
          </div>
        </div>
        <button v-else type="button" class="gate-button" :disabled="busy" @click="createSetup">
          <QrCode :size="17" />
          生成绑定二维码
        </button>
        <CodeInput v-model="code" :error="!!errorText" :success="successGlow" />
        <button type="button" class="gate-button" :disabled="busy || code.length !== 6" @click="confirmSetup">
          <Loader2 v-if="busy" class="animate-spin" :size="17" />
          <ShieldCheck v-else :size="17" />
          确认绑定
        </button>
      </template>

      <template v-else>
        <CodeInput v-model="code" :error="!!errorText" :success="successGlow" @submit="verify" />
        <label v-if="state.allow_remember_device" class="remember-row flex items-center gap-3 text-sm text-zinc-600 select-none">
          <input v-model="remember" type="checkbox" class="remember-checkbox rounded">
          <span>记住此设备 {{ state.remember_days }} 天</span>
        </label>
        <button type="button" class="gate-button" :disabled="busy || code.length !== 6" @click="verify">
          <Loader2 v-if="busy" class="animate-spin" :size="17" />
          <ShieldCheck v-else :size="17" />
          验证并进入系统
        </button>
      </template>

      <Transition name="gate-msg">
        <div v-if="errorText" class="gate-message is-error">
          <CircleAlert :size="16" />
          <span>{{ errorText }}</span>
        </div>
      </Transition>
      <Transition name="gate-msg">
        <div v-if="hintText" class="gate-message is-info">
          <Info :size="16" />
          <span>{{ hintText }}</span>
        </div>
      </Transition>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Ban, CircleAlert, Copy, Info, Loader2, QrCode, ShieldCheck, UnlockKeyhole } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { securityGateApi } from '../api'

const CodeInput = defineComponent({
  props: {
    modelValue: { type: String, default: '' },
    error: { type: Boolean, default: false },
    success: { type: Boolean, default: false }
  },
  emits: ['update:modelValue', 'submit'],
  setup(props, { emit }) {
    const boxes = Array.from({ length: 6 }, () => ref(null))
    const digits = computed(() => props.modelValue.padEnd(6, ' ').slice(0, 6).split(''))
    function nextDigits() {
      return props.modelValue.padEnd(6, ' ').slice(0, 6).split('').map(item => item.trim())
    }
    function syncDigits(items) {
      emit('update:modelValue', items.join('').replace(/\D/g, '').slice(0, 6))
    }
    async function focusInput(index) {
      await nextTick()
      const input = boxes[Math.max(0, Math.min(index, 5))]?.value
      input?.focus()
      input?.select?.()
    }
    function setValue(index, value) {
      const nums = String(value || '').replace(/\D/g, '')
      const next = nextDigits()
      if (!nums) {
        next[index] = ''
        syncDigits(next)
        return
      }
      for (let i = 0; i < nums.length && index + i < 6; i++) {
        next[index + i] = nums[i]
      }
      syncDigits(next)
      focusInput(Math.min(index + nums.length, 5))
    }
    function onKey(index, event) {
      if (event.key === 'Enter') emit('submit')
      if (event.key === 'Backspace' && !digits.value[index]?.trim() && index > 0) {
        const next = nextDigits()
        next[index - 1] = ''
        syncDigits(next)
        focusInput(index - 1)
      }
      if (event.key === 'ArrowLeft' && index > 0) {
        event.preventDefault()
        focusInput(index - 1)
      }
      if (event.key === 'ArrowRight' && index < 5) {
        event.preventDefault()
        focusInput(index + 1)
      }
    }
    return () => h('div', {
      class: [
        'otp-grid',
        props.error && 'is-error',
        props.success && 'is-success'
      ]
    },
      digits.value.map((digit, index) => h('input', {
        ref: boxes[index],
        class: 'otp-input',
        value: digit.trim(),
        inputmode: 'numeric',
        maxlength: 6,
        autocomplete: index === 0 ? 'one-time-code' : 'off',
        type: 'text',
        ariaLabel: '验证码数字',
        onInput: event => setValue(index, event.target.value),
        onPaste: event => {
          event.preventDefault()
          setValue(index, event.clipboardData?.getData('text') || '')
        },
        onKeydown: event => onKey(index, event)
      }))
    )
  }
})

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const busy = ref(false)
const state = ref({})
const setup = ref({})
const code = ref('')
const remember = ref(false)
const errorText = ref('')
const hintText = ref('')
const successGlow = ref(false)

const blocked = computed(() => Boolean(state.value?.blocked))

onMounted(loadState)

async function loadState() {
  loading.value = true
  try {
    state.value = await securityGateApi.status()
    if (state.value.enabled && !state.value.bound && state.value.has_pending_setup) {
      await createSetup()
    }
  } finally {
    loading.value = false
  }
}

async function createSetup() {
  busy.value = true
  errorText.value = ''
  try {
    setup.value = await securityGateApi.createSetup()
    hintText.value = '扫码后输入 App 当前验证码完成绑定。'
  } catch (error) {
    errorText.value = error.response?.data?.detail || error.message || '生成二维码失败'
  } finally {
    busy.value = false
  }
}

async function confirmSetup() {
  busy.value = true
  errorText.value = ''
  try {
    await securityGateApi.confirmSetup(code.value)
    successGlow.value = true
    hintText.value = '绑定完成。请在设置页开启安全门禁。'
    code.value = ''
    await loadState()
  } catch (error) {
    errorText.value = error.response?.data?.detail || '验证码错误'
  } finally {
    busy.value = false
  }
}

async function verify() {
  if (code.value.length !== 6 || busy.value) return
  busy.value = true
  errorText.value = ''
  try {
    await securityGateApi.verify({ code: code.value, remember: remember.value })
    successGlow.value = true
    enterApp()
  } catch (error) {
    code.value = ''
    const data = error.response?.data || {}
    if (data.blocked) {
      router.replace('/blocked')
      return
    }
    errorText.value = data.remaining_attempts != null
      ? `${data.message || '验证码错误'}，剩余 ${data.remaining_attempts} 次`
      : (data.message || data.detail || '验证码错误')
  } finally {
    busy.value = false
  }
}

function enterApp() {
  router.replace(String(route.query.next || '/'))
}

function goBlocked() {
  router.replace('/blocked')
}

async function copySecret() {
  await navigator.clipboard.writeText(setup.value.secret || '')
  ElMessage.success('密钥已复制')
}
</script>

<style scoped>
.gate-page {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
}

.glass-card {
  position: relative;
  overflow: hidden;
  isolation: isolate;
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.22) 0%,
      rgba(255, 255, 255, 0.12) 26%,
      rgba(255, 255, 255, 0.055) 52%,
      rgba(255, 255, 255, 0.16) 100%
    );
  backdrop-filter: blur(230px) saturate(340%) brightness(1.16) contrast(1.04);
  border: 1px solid rgba(255, 255, 255, 0.58);
  box-shadow:
    0 70px 190px rgba(15, 23, 42, 0.10),
    inset 0 44px 90px rgba(255, 255, 255, 0.26),
    inset 0 -54px 100px rgba(255, 255, 255, 0.10),
    inset 0 3px 0 rgba(255, 255, 255, 0.92),
    inset 0 -2px 0 rgba(255, 255, 255, 0.14),
    0 0 0 1px rgba(255, 255, 255, 0.22);
  animation: panelIn 520ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

.glass-card::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -1;
  border-radius: inherit;
  background:
    linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.88) 0%,
      rgba(255, 255, 255, 0.30) 18%,
      rgba(255, 255, 255, 0.06) 48%,
      rgba(255, 255, 255, 0.18) 100%
    ),
    radial-gradient(circle at 18% 8%, rgba(255, 255, 255, 0.55), transparent 28%),
    radial-gradient(circle at 90% 82%, rgba(255, 255, 255, 0.16), transparent 32%);
  mix-blend-mode: screen;
  pointer-events: none;
}

.glass-card::after {
  content: "";
  position: absolute;
  inset: 1px;
  border-radius: inherit;
  border: 1px solid rgba(255, 255, 255, 0.36);
  pointer-events: none;
}

.icon-glass {
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.30),
      rgba(255, 255, 255, 0.08)
    );
  backdrop-filter: blur(90px) saturate(260%);
  border: 1px solid rgba(255, 255, 255, 0.56);
  box-shadow:
    inset 0 18px 44px rgba(255, 255, 255, 0.24),
    inset 0 -14px 34px rgba(255, 255, 255, 0.08),
    0 18px 42px rgba(15, 23, 42, 0.08);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.icon-glass:hover {
  transform: translateY(-2px) scale(1.03);
  box-shadow:
    inset 0 18px 44px rgba(255, 255, 255, 0.28),
    inset 0 -14px 34px rgba(255, 255, 255, 0.10),
    0 22px 48px rgba(15, 23, 42, 0.10);
}

.otp-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
  animation: codeIn 460ms 90ms both cubic-bezier(0.34, 1.56, 0.64, 1);
}

:deep(.otp-input) {
  width: 100%;
  height: 82px;
  outline: none !important;
  text-align: center;
  color: #111827;
  font-size: 34px;
  line-height: 1;
  font-weight: 500;
  letter-spacing: 0;
  caret-color: #111827;
  border-radius: 24px;
  border: 1px solid rgba(203, 213, 225, 0.72);
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.98) 0%,
      rgba(255, 255, 255, 0.86) 46%,
      rgba(248, 250, 252, 0.78) 100%
    );
  backdrop-filter: blur(90px) saturate(220%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.96),
    inset 0 -18px 34px rgba(241, 245, 249, 0.36),
    0 16px 34px rgba(15, 23, 42, 0.055),
    0 1px 2px rgba(15, 23, 42, 0.04);
  appearance: none;
  -webkit-appearance: none;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease, background .22s ease;
  animation: digitIn 420ms both cubic-bezier(0.34, 1.56, 0.64, 1);
}

:deep(.otp-input:focus) {
  transform: translateY(-3px) scale(1.025);
  border-color: rgba(17, 24, 39, 0.30);
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 1) 0%,
      rgba(255, 255, 255, 0.94) 48%,
      rgba(248, 250, 252, 0.86) 100%
    );
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 1),
    inset 0 -16px 32px rgba(241, 245, 249, 0.28),
    0 20px 42px rgba(15, 23, 42, 0.08),
    0 0 0 4px rgba(17, 24, 39, 0.045);
}

:deep(.otp-input::-webkit-outer-spin-button),
:deep(.otp-input::-webkit-inner-spin-button) {
  margin: 0;
  appearance: none;
}

:deep(.otp-input:nth-child(1)) { animation-delay: 80ms; }
:deep(.otp-input:nth-child(2)) { animation-delay: 120ms; }
:deep(.otp-input:nth-child(3)) { animation-delay: 160ms; }
:deep(.otp-input:nth-child(4)) { animation-delay: 200ms; }
:deep(.otp-input:nth-child(5)) { animation-delay: 240ms; }
:deep(.otp-input:nth-child(6)) { animation-delay: 280ms; }

.otp-grid.is-error {
  animation: shake 360ms ease;
}

.otp-grid.is-error :deep(.otp-input) {
  border-color: rgba(239, 68, 68, 0.48);
  box-shadow:
    inset 0 26px 60px rgba(255, 255, 255, 0.26),
    0 0 0 6px rgba(239, 68, 68, 0.08),
    0 22px 44px rgba(239, 68, 68, 0.08);
}

.otp-grid.is-success :deep(.otp-input) {
  animation: successPulse 520ms ease;
  border-color: rgba(17, 24, 39, 0.18);
}

.gate-state,
.gate-alert,
.gate-message,
.remember-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.gate-state,
.gate-alert {
  min-height: 50px;
  padding: 14px 16px;
  margin-bottom: 24px;
  border-radius: 22px;
  color: #52525b;
  font-size: 14px;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.62);
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.26) 0%,
      rgba(255, 255, 255, 0.10) 48%,
      rgba(255, 255, 255, 0.055) 100%
    );
  backdrop-filter: blur(130px) saturate(280%);
  box-shadow:
    inset 0 18px 44px rgba(255, 255, 255, 0.22),
    0 18px 36px rgba(15, 23, 42, 0.06);
}

.gate-alert.is-danger {
  color: #b91c1c;
  background: #fff1f2;
}

.setup-box {
  display: grid;
  gap: 14px;
  padding: 18px;
  margin-bottom: 24px;
  border-radius: 28px;
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.26) 0%,
      rgba(255, 255, 255, 0.10) 48%,
      rgba(255, 255, 255, 0.055) 100%
    );
  border: 1px solid rgba(255, 255, 255, 0.62);
  box-shadow:
    inset 0 26px 60px rgba(255, 255, 255, 0.28),
    inset 0 -24px 48px rgba(255, 255, 255, 0.08),
    0 22px 44px rgba(15, 23, 42, 0.07);
  backdrop-filter: blur(130px) saturate(280%);
  animation: panelIn 420ms ease;
}

.setup-box img {
  width: 190px;
  height: 190px;
  margin: 0 auto;
  border-radius: 8px;
}

.setup-secret {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #1d1d1f;
  font-size: 12px;
  word-break: break-all;
  letter-spacing: 0;
}

.setup-secret button,
.gate-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.setup-secret button {
  flex: 0 0 auto;
  height: 32px;
  padding: 0 10px;
  border-radius: 980px;
  color: #111827;
  background: rgba(255, 255, 255, 0.24);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.46);
}

.gate-button {
  width: 100%;
  height: 58px;
  margin-top: 24px;
  border-radius: 980px;
  color: #ffffff;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0;
  background: rgba(17, 24, 39, 0.88);
  box-shadow:
    0 18px 35px rgba(15, 23, 42, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.18);
}

.gate-button:hover:not(:disabled),
.setup-secret button:hover {
  transform: translateY(-1px);
}

.gate-button:hover:not(:disabled) {
  background: rgba(17, 24, 39, 0.94);
  box-shadow:
    0 22px 42px rgba(15, 23, 42, 0.17),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.gate-button:hover:not(:disabled) svg,
.setup-secret button:hover svg {
  transform: rotate(-8deg) scale(1.08);
}

.gate-button svg,
.setup-secret button svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.gate-button:active:not(:disabled) {
  transform: translateY(0) scale(0.98);
}

.gate-button:disabled {
  opacity: 1;
  background: rgba(17, 24, 39, 0.34);
  cursor: not-allowed;
}

.gate-button.is-muted {
  color: #111827;
  background: rgba(255, 255, 255, 0.24);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.46);
}

.remember-row {
  margin-top: 22px;
}

.remember-checkbox {
  width: 16px;
  height: 16px;
  accent-color: #111827;
}

.gate-message {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: 18px;
  font-size: 13px;
  letter-spacing: 0;
  justify-content: center;
  backdrop-filter: blur(90px) saturate(220%);
}

.gate-message.is-error {
  color: #b91c1c;
  background: #fff1f2;
}

.gate-message.is-info {
  color: #1f2937;
  background: rgba(255, 255, 255, 0.34);
}

.gate-msg-enter-active,
.gate-msg-leave-active {
  transition: all 220ms ease;
}

.gate-msg-enter-from,
.gate-msg-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@keyframes panelIn {
  from { opacity: 0; transform: translateY(10px) scale(0.99); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes codeIn {
  from { opacity: 0; transform: translateY(12px) scale(0.98); filter: blur(4px); }
  to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}

@keyframes digitIn {
  from { opacity: 0; transform: translateY(8px) scale(0.94); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes successPulse {
  0% { transform: scale(1); }
  42% { transform: scale(1.04); }
  100% { transform: scale(1); }
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-7px); }
  50% { transform: translateX(6px); }
  75% { transform: translateX(-4px); }
}

@media (max-width: 560px) {
  .gate-page {
    padding: 18px 14px;
    align-items: start;
  }
  .gate-panel {
    border-radius: 30px;
  }
  .otp-grid {
    gap: 8px;
  }
  :deep(.otp-input) {
    height: 58px;
    border-radius: 18px;
    font-size: 24px;
  }
}
</style>
