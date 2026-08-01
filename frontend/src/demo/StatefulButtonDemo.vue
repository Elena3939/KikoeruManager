<template>
  <div class="flex min-h-40 w-full items-center justify-center gap-3">
    <StatefulButton tone="primary" @click="handleClick">
      发送消息
    </StatefulButton>
    <StatefulButton tone="sky" @click="handleClick">
      同步任务
    </StatefulButton>
    <StatefulButton tone="neutral" @click="handleClick">
      保存设置
    </StatefulButton>
  </div>
</template>

<script setup>
import StatefulButton from '@/components/ui/stateful-button.vue'

function handleClick() {
  return new Promise((resolve) => {
    window.setTimeout(resolve, 4000)
  })
}
</script>
