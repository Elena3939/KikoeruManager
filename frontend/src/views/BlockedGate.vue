<template>
  <section class="blocked-page">
    <div class="blocked-card">
      <div class="blocked-icon">
        <ShieldX :size="34" :stroke-width="2.4" />
      </div>
      <p class="blocked-kicker">Security Gate</p>
      <h1>访问已被阻止</h1>
      <p class="blocked-copy">
        当前来源因多次验证失败已被系统永久拉黑。若这是误操作，请在服务器端或已验证设备的设置页解除黑名单。
      </p>
      <div v-if="info" class="blocked-detail">
        <div>
          <span>IP 地址</span>
          <strong>{{ info.ip_address || '未知' }}</strong>
        </div>
        <div>
          <span>失败次数</span>
          <strong>{{ info.failure_count ?? '-' }}</strong>
        </div>
        <div>
          <span>拉黑时间</span>
          <strong>{{ formatTime(info.blocked_at) }}</strong>
        </div>
      </div>
      <button type="button" class="blocked-button" @click="refresh">
        <RefreshCw :size="16" />
        重新检查状态
      </button>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { RefreshCw, ShieldX } from 'lucide-vue-next'
import { securityGateApi } from '../api'

const info = ref(null)

onMounted(refresh)

async function refresh() {
  const state = await securityGateApi.status()
  info.value = state?.blocked_info || null
}

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}
</script>

<style scoped>
.blocked-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  color: #fff7ed;
  background:
    radial-gradient(circle at 36% 22%, rgba(248, 113, 113, 0.2), transparent 28%),
    radial-gradient(circle at 76% 78%, rgba(251, 146, 60, 0.18), transparent 30%),
    linear-gradient(135deg, #12070a 0%, #1f1720 48%, #0f172a 100%);
}

.blocked-card {
  width: min(100%, 520px);
  padding: 36px;
  border: 1px solid rgba(254, 202, 202, 0.24);
  border-radius: 28px;
  background: rgba(30, 18, 24, 0.72);
  box-shadow: 0 28px 90px rgba(0, 0, 0, 0.44), inset 0 1px 0 rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(24px);
  animation: blockedIn 520ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

.blocked-icon {
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  margin-bottom: 20px;
  border-radius: 22px;
  color: #fecaca;
  background: linear-gradient(180deg, rgba(248, 113, 113, 0.24), rgba(251, 146, 60, 0.14));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 18px 42px rgba(248, 113, 113, 0.16);
}

.blocked-kicker {
  margin: 0 0 8px;
  color: #fdba74;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 32px;
  letter-spacing: 0;
}

.blocked-copy {
  margin: 14px 0 22px;
  color: rgba(255, 237, 213, 0.76);
  line-height: 1.8;
}

.blocked-detail {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.38);
  border: 1px solid rgba(254, 202, 202, 0.14);
}

.blocked-detail div {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  font-size: 13px;
}

.blocked-detail span {
  color: rgba(255, 237, 213, 0.58);
}

.blocked-detail strong {
  color: #fff7ed;
  font-weight: 700;
  text-align: right;
}

.blocked-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  height: 48px;
  margin-top: 20px;
  border: 0;
  border-radius: 17px;
  color: #fff7ed;
  font-weight: 700;
  cursor: pointer;
  background: linear-gradient(180deg, #fb923c 0%, #ef4444 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28), 0 16px 38px rgba(239, 68, 68, 0.26);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.blocked-button:hover {
  transform: translateY(-2px) scale(1.02);
}

.blocked-button:active {
  transform: translateY(0) scale(0.97);
}

@keyframes blockedIn {
  from { opacity: 0; transform: translateY(18px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
