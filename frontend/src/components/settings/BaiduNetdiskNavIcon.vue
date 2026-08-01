<template>
  <svg
    class="baidu-netdisk-nav-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M7.1 10.1c-2 .9-3.3 2.3-3.1 4 .2 1.8 2 3 4.2 2.8 2-.2 3.4-1.6 3.2-3.3-.2-1.8-2-4.4-4.3-3.5Z" />
    <path d="M16.9 10.1c2 .9 3.3 2.3 3.1 4-.2 1.8-2 3-4.2 2.8-2-.2-3.4-1.6-3.2-3.3.2-1.8 2-4.4 4.3-3.5Z" />
    <path d="M9.3 8.7c.4-2.3 1.4-3.7 2.7-3.7s2.3 1.4 2.7 3.7c.3 2-1 3.6-2.7 3.6S9 10.7 9.3 8.7Z" />
    <path d="M8.2 17.3c1.1.9 2.4 1.4 3.8 1.4s2.7-.5 3.8-1.4" />
  </svg>
</template>

<script setup>
defineProps({
  size: { type: [Number, String], default: 15 },
  strokeWidth: { type: [Number, String], default: 2.2 }
})
</script>

<style scoped>
.baidu-netdisk-nav-icon {
  display: block;
  overflow: visible;
}
</style>
