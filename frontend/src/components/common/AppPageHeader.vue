<template>
  <header class="app-page-header">
    <div class="app-page-head-left">
      <div v-if="icon" class="app-page-icon" :style="{ color: iconColor }" aria-hidden="true">
        <component :is="icon" :size="iconSize" :stroke-width="2.2" />
      </div>
      <div class="min-w-0">
        <h1 class="app-page-title">{{ title }}</h1>
        <p v-if="subtitle" class="app-page-subtitle">{{ subtitle }}</p>
      </div>
    </div>

    <div v-if="$slots.default" class="app-page-head-right">
      <slot />
    </div>
  </header>
</template>

<script setup>
// 全局共享的页面顶栏。
// 视觉规范：
//   - 图标无背景，仅用 color 着色（参考库存页 #1d4ed8 蓝、问题作品页 #b45309 琥珀）
//   - 标题 22px / 700 / 黑色 #0f172a
//   - 副标题 12.5px / 灰色 #64748b
//   - 右侧 slot 默认放 chip / 操作按钮，flex-wrap 自适应
// 用法：
//   <AppPageHeader :icon="Database" title="库存文件管理" subtitle="...">
//     <span class="lib-chip">...</span>
//   </AppPageHeader>
defineOptions({ name: 'AppPageHeader' })

defineProps({
  // lucide-vue-next 的图标组件（也兼容任意可作为 component :is 的引用）
  icon: { type: [Object, Function], default: null },
  // 图标颜色，默认与库存页一致；建议各页面按语义自定
  iconColor: { type: String, default: '#1d4ed8' },
  // 图标大小（顶部容器固定 44×44，icon 默认 20）
  iconSize: { type: Number, default: 20 },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>

<style scoped>
.app-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.app-page-head-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.app-page-head-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.app-page-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  /* 图标无任何背景 / 阴影 / 边框，颜色由 :style 接管 */
}

.app-page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.4px;
  color: #0f172a;
  line-height: 1.2;
}

.app-page-subtitle {
  margin: 2px 0 0;
  font-size: 12.5px;
  color: #64748b;
  line-height: 1.45;
}
</style>
