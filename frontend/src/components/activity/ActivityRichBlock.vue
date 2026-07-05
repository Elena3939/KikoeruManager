<template>
  <!-- 关键字段（detail highlights）—— 头部对齐文件树样式（eyebrow + title） -->
  <section v-if="highlights.length" class="panel">
    <div class="entry-section-head">
      <div class="entry-section-head-copy">
        <div class="entry-eyebrow">概览</div>
        <div class="entry-section-title">关键字段（{{ highlights.length }} 项）</div>
      </div>
    </div>
    <dl class="highlight-grid">
      <div
        v-for="hl in highlights"
        :key="`hl-${hl.k}`"
        class="highlight-row"
        :class="{ 'is-numeric': metricSplit(hl.v).unit, 'is-wide': isWideHighlight(hl.v) }"
      >
        <dt class="highlight-label">{{ hl.k }}</dt>
        <dd class="highlight-value" :class="{ 'is-short-value': !isWideHighlight(hl.v) }">
          <template v-if="metricSplit(hl.v).unit">
            <span class="highlight-num">{{ metricSplit(hl.v).num }}</span>
            <span class="highlight-unit">{{ metricSplit(hl.v).unit }}</span>
          </template>
          <template v-else>{{ hl.v }}</template>
        </dd>
      </div>
    </dl>
  </section>

  <!-- 路径对比（重命名 / 删除） -->
  <section v-if="pathCompare" class="panel">
    <div class="panel-head">
      <ArrowRightLeft :size="13" :stroke-width="2.4" />
      <span>{{ pathCompare.title }}</span>
      <span
        v-if="pathCompare.opTag"
        class="ml-1 inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset"
        :class="pathOpTagClasses(pathCompare.opTagClass)"
      >{{ pathCompare.opTag }}</span>
    </div>
    <div class="flex flex-col gap-2">
      <div class="flex items-start gap-2">
        <span class="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500/80 shrink-0 pt-1 w-[44px]">变更前</span>
        <code class="flex-1 min-w-0 break-all text-[12px] font-mono leading-relaxed text-slate-700 bg-slate-50/70 ring-1 ring-inset ring-slate-200/40 px-2.5 py-1.5 rounded-md">{{ pathCompare.beforePath || '—' }}</code>
      </div>
      <div class="flex items-start gap-2">
        <span class="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500/80 shrink-0 pt-1 w-[44px]">变更后</span>
        <code class="flex-1 min-w-0 break-all text-[12px] font-mono leading-relaxed text-slate-700 bg-slate-50/70 ring-1 ring-inset ring-slate-200/40 px-2.5 py-1.5 rounded-md">{{ pathCompare.afterPath || '—' }}</code>
      </div>
      <div
        v-if="pathCompare.reason || pathCompareReason"
        class="text-[12px] leading-relaxed px-2.5 py-1.5 rounded-md ring-1 ring-inset"
        :class="pathReasonClasses(pathCompareCls)"
      >{{ pathCompare.reason || pathCompareReason }}</div>
    </div>
  </section>

  <!-- 字幕配对工作台跳转卡片 -->
  <section
    v-if="showPairWorkbenchPanel"
    class="panel pair-workbench-card"
    :class="{ 'is-awaiting': pairWorkbench.awaiting }"
  >
    <div class="pair-workbench-layout">
      <div class="pair-workbench-copy">
        <div class="pair-workbench-badge">{{ pairWorkbench.awaiting ? '待继续处理' : '可查看工作台' }}</div>
        <div class="pair-workbench-title">{{ pairWorkbench.title }}</div>
        <p class="pair-workbench-desc">{{ pairWorkbench.description }}</p>
        <div v-if="pairWorkbench.chips.length" class="pair-workbench-chips">
          <span
            v-for="chip in pairWorkbench.chips"
            :key="`pwc-${chip}`"
            class="pair-workbench-chip"
          >{{ chip }}</span>
        </div>
      </div>
      <el-button
        type="primary"
        size="default"
        class="pair-workbench-button"
        @click="openSubtitlePairWorkbench"
      >
        <ArrowUpRight :size="14" :stroke-width="2.4" class="mr-1" />
        {{ pairWorkbench.buttonText }}
      </el-button>
    </div>
  </section>

  <!-- 字幕配对结果 -->
  <section v-if="pairResult" class="panel">
    <div class="panel-head">
      <GitCompareArrows :size="13" :stroke-width="2.4" />
      <span>{{ pairResult.title }}</span>
      <span
        class="ml-1 inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset"
        :class="pairStatusClasses(pairResult.status)"
      >{{ pairResult.statusLabel }}</span>
      <button
        v-if="pairWorkbench"
        type="button"
        class="pair-result-open-btn"
        @click="openSubtitlePairWorkbench"
      >
        <ArrowUpRight :size="12" :stroke-width="2.4" />
        <span>{{ pairWorkbench.buttonText || '打开配对面板' }}</span>
      </button>
    </div>
    <p v-if="pairResult.summary" class="text-[12.5px] leading-relaxed text-slate-700 mb-2.5">{{ pairResult.summary }}</p>
    <div class="pair-metric-grid">
      <div
        v-for="metric in pairResult.metrics"
        :key="`pr-${metric.label}`"
        class="pair-metric-card"
      >
        <div class="pair-metric-label">{{ metric.label }}</div>
        <div class="pair-metric-value">{{ metric.value }}</div>
      </div>
    </div>
    <div v-if="pairResult.changes.length" class="flex flex-col gap-1.5">
      <div class="text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500/80">配对映射</div>
      <div
        v-for="(change, idx) in pairResult.changes.slice(0, 8)"
        :key="`pchg-${idx}`"
        class="text-[11.5px] leading-relaxed font-mono px-2 py-1 rounded-md bg-slate-50/50 ring-1 ring-inset ring-slate-200/30"
      >
        <span class="text-slate-500">{{ change.audio_after || change.audio_before || '?' }}</span>
        <span class="mx-1 text-slate-400">←</span>
        <span class="text-slate-700">{{ change.subtitle_after || change.subtitle_before || '?' }}</span>
      </div>
      <span v-if="pairResult.changes.length > 8" class="text-[11px] text-slate-500">…还有 {{ pairResult.changes.length - 8 }} 项</span>
    </div>
  </section>

  <!-- 字幕批量工作台 -->
  <section v-if="subtitleBatchModel" class="panel">
    <div class="panel-head">
      <Layers :size="13" :stroke-width="2.4" />
      <span>批量工作台</span>
      <span class="panel-head-count">{{ subtitleBatchModel.items.length }}</span>
    </div>
    <p class="text-[12.5px] leading-relaxed text-slate-600 mb-2.5">勾选要继续处理的 RJ，直接带回库存里的字幕工作台。这里只展示批量子任务，不展示单个 RJ 的配对映射。</p>
    <div class="flex flex-wrap gap-1.5 mb-2.5">
      <span class="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60">
        <CheckCircle2 :size="11" :stroke-width="2.5" />
        已配对 {{ subtitleBatchModel.pairedCount }}
      </span>
      <span class="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60">
        <Clock :size="11" :stroke-width="2.5" />
        待配对 {{ subtitleBatchModel.awaitingCount }}
      </span>
      <span class="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60">
        合计 {{ subtitleBatchModel.items.length }}
      </span>
    </div>
    <div class="flex items-center gap-3 flex-wrap mb-2.5 px-3 py-2 rounded-lg bg-slate-50/50 ring-1 ring-inset ring-slate-200/40">
      <label class="inline-flex items-center gap-1.5 text-[12px] text-slate-600 cursor-pointer select-none">
        <input
          v-model="batchAwaitingOnly"
          type="checkbox"
          class="accent-slate-500"
        >
        仅显示未配对
      </label>
      <button
        type="button"
        class="text-[12px] font-medium text-slate-700 hover:text-slate-900 transition-colors"
        @click="selectAwaitingBatch"
      >全选未配对</button>
      <label class="inline-flex items-center gap-1.5 text-[12px] text-slate-600 cursor-pointer select-none ml-auto">
        <input
          type="checkbox"
          :checked="allBatchSelected"
          class="accent-slate-500"
          @change="toggleAllBatch($event.target.checked)"
        >
        全选当前
      </label>
      <el-button
        type="primary"
        size="small"
        :disabled="!selectedBatchItems.length"
        class="transition-all hover:-translate-y-0.5 hover:shadow-md"
        @click="openSubtitleBatchWorkbench"
      >
        <ArrowUpRight :size="13" :stroke-width="2.4" class="mr-0.5" />
        将选中项带到工作台
      </el-button>
    </div>
    <div class="flex flex-col gap-1.5 max-h-[440px] overflow-y-auto pr-1">
      <label
        v-for="item in visibleBatchItems"
        :key="item.key"
        class="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-white ring-1 ring-inset ring-slate-200/50 hover:ring-slate-300/70 hover:shadow-sm transition-all cursor-pointer"
      >
        <input
          v-model="selectedBatchKeys"
          type="checkbox"
          :value="item.key"
          class="mt-1 shrink-0 accent-slate-500"
        >
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="inline-flex items-center px-1.5 py-[2px] rounded text-[11px] font-mono font-semibold tracking-tight bg-slate-100/70 text-slate-700 ring-1 ring-inset ring-slate-200/60">{{ item.rjcode || '未知RJ' }}</span>
            <span
              class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset"
              :class="batchStateClasses(item.stateClass)"
            >{{ item.stateLabel }}</span>
            <span v-if="item.createdAt" class="text-[11px] text-slate-400 tabular-nums ml-auto">{{ formatDateTime(item.createdAt) }}</span>
          </div>
          <div class="text-[12.5px] font-medium text-slate-700 mt-1 truncate">{{ item.folderName || '—' }}</div>
          <div class="text-[11.5px] text-slate-500 leading-relaxed mt-0.5 line-clamp-2">{{ item.summary || '—' }}</div>
        </div>
      </label>
    </div>
  </section>

  <!-- 邮件监听新作 -->
  <section v-if="emailWatcherModel" class="panel">
    <div class="panel-head">
      <Mail :size="13" :stroke-width="2.4" />
      <span>新作卡片</span>
      <span class="panel-head-count">{{ emailWatcherModel.totalCount }}</span>
    </div>
    <div class="flex items-start gap-3 flex-wrap mb-2.5">
      <div class="flex-1 min-w-0">
        <div class="text-[14px] font-bold tracking-tight text-slate-900">监视新作</div>
        <div class="text-[12.5px] leading-relaxed text-slate-600 mt-1">{{ emailWatcherModel.circleNamesText || '本批次未解析到社团名' }}</div>
      </div>
      <div class="flex flex-wrap gap-1 shrink-0">
        <span class="email-watch-stat is-stat-default">邮件 {{ emailWatcherModel.mailCount }}</span>
        <span class="email-watch-stat is-stat-default">新作 {{ emailWatcherModel.totalCount }}</span>
        <span class="email-watch-stat is-stat-success">成功 {{ emailWatcherModel.successCount }}</span>
        <span v-if="emailWatcherModel.failedCount" class="email-watch-stat is-stat-failed">失败 {{ emailWatcherModel.failedCount }}</span>
      </div>
    </div>
    <div v-if="emailWatcherModel.mailSubjects.length" class="flex flex-wrap gap-1 mb-2.5">
      <span
        v-for="subject in emailWatcherModel.mailSubjects"
        :key="`mws-${subject}`"
        class="email-watch-subject"
      >{{ subject }}</span>
    </div>
    <div class="flex flex-col gap-3">
      <article
        v-for="item in emailWatcherModel.items"
        :key="`ew-${item.rjcode}-${item.productUrl || item.title}`"
        class="email-watch-card group flex gap-3.5 p-3 bg-white"
        :class="item.statusKey === 'failed' ? 'is-failed' : (item.statusKey === 'success' ? 'is-success' : 'is-default')"
      >
        <div class="email-watch-cover w-[120px] h-[120px] shrink-0 overflow-hidden bg-slate-100">
          <img
            v-if="item.coverUrl"
            :src="item.coverUrl"
            :alt="item.title || item.rjcode"
            loading="lazy"
            class="w-full h-full object-cover transition-transform duration-300 ease-out group-hover:scale-[1.03]"
            @error="onEmailWatchCoverError($event, item)"
          >
          <div v-else class="w-full h-full flex items-center justify-center text-slate-400">
            <ImageIcon :size="22" :stroke-width="1.8" />
          </div>
        </div>
        <div class="flex-1 min-w-0 flex flex-col gap-1">
          <div class="flex items-center justify-between gap-2">
            <span class="email-watch-rj">{{ item.rjcode || '—' }}</span>
            <span
              class="email-watch-status"
              :class="item.statusKey === 'success' ? 'is-status-success' : (item.statusKey === 'failed' ? 'is-status-failed' : 'is-status-default')"
            >{{ item.statusLabel }}</span>
          </div>
          <a
            v-if="item.productUrl"
            :href="item.productUrl"
            target="_blank"
            rel="noopener"
            class="text-[14px] font-bold leading-snug tracking-tight text-slate-900 hover:text-slate-700 transition-colors line-clamp-2"
          >{{ item.title || item.rjcode || '未命名作品' }}</a>
          <div v-else class="text-[14px] font-bold leading-snug tracking-tight text-slate-900 line-clamp-2">{{ item.title || item.rjcode || '未命名作品' }}</div>
          <div class="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-slate-600 leading-relaxed">
            <span class="inline-flex items-center gap-1 min-w-0 max-w-full">
              <Users :size="12" :stroke-width="2" class="text-slate-400 shrink-0" />
              <span class="truncate">{{ item.circleName || '未知社团' }}</span>
            </span>
            <span class="inline-flex items-center gap-1">
              <Clock :size="12" :stroke-width="2" class="text-slate-400 shrink-0" />
              <span class="tabular-nums">{{ item.releaseDate || '发售日待定' }}</span>
            </span>
          </div>
          <div class="flex flex-wrap gap-1 mt-auto pt-0.5">
            <span v-if="item.priceText" class="email-watch-chip is-chip-price">{{ item.priceText }}</span>
            <span v-if="item.workType" class="email-watch-chip is-chip-type">{{ item.workType }}</span>
            <span v-if="item.indexMode" class="email-watch-chip is-chip-index">{{ item.indexMode }}</span>
            <span
              v-if="item.backfillMode"
              class="email-watch-chip"
              :class="item.backfillTriggered ? 'is-chip-backfill-on' : 'is-chip-backfill-off'"
            >{{ item.backfillMode }}</span>
          </div>
        </div>
      </article>
    </div>
  </section>

  <!-- 删除统计：大卡片横向统计条（数字大、单位小、底部跟一组路径行） -->
  <section v-if="filterDeleteMetrics.length" class="panel">
    <div class="entry-section-head">
      <div class="entry-section-head-copy">
        <div class="entry-eyebrow">删除</div>
        <div class="entry-section-title">删除统计（{{ filterDeleteMetrics.length }} 项）</div>
      </div>
    </div>
    <div v-if="filterDeleteNumeric.length" class="metric-strip">
      <div
        v-for="item in filterDeleteNumeric"
        :key="`fdm-${item.k}`"
        class="metric-cell"
      >
        <div class="metric-cell-label">{{ item.k }}</div>
        <div class="metric-cell-value">
          <template v-if="metricSplit(item.v).unit">
            <span class="metric-num">{{ metricSplit(item.v).num }}</span>
            <span class="metric-unit">{{ metricSplit(item.v).unit }}</span>
          </template>
          <span v-else class="metric-num">{{ item.v }}</span>
        </div>
      </div>
    </div>
    <dl v-if="filterDeleteTextual.length" class="metric-tail">
      <div
        v-for="item in filterDeleteTextual"
        :key="`fdt-${item.k}`"
        class="metric-tail-row"
      >
        <dt class="metric-tail-k">{{ item.k }}</dt>
        <dd class="metric-tail-v">{{ item.v }}</dd>
      </div>
    </dl>
  </section>

  <!-- 上传统计：大卡片横向统计条 -->
  <section v-if="uploadMetrics.length" class="panel">
    <div class="entry-section-head">
      <div class="entry-section-head-copy">
        <div class="entry-eyebrow">上传</div>
        <div class="entry-section-title">上传统计（{{ uploadMetrics.length }} 项）</div>
      </div>
    </div>
    <div v-if="uploadNumeric.length" class="metric-strip">
      <div
        v-for="item in uploadNumeric"
        :key="`upm-${item.k}`"
        class="metric-cell"
      >
        <div class="metric-cell-label">{{ item.k }}</div>
        <div class="metric-cell-value">
          <template v-if="metricSplit(item.v).unit">
            <span class="metric-num">{{ metricSplit(item.v).num }}</span>
            <span class="metric-unit">{{ metricSplit(item.v).unit }}</span>
          </template>
          <span v-else class="metric-num">{{ item.v }}</span>
        </div>
      </div>
    </div>
    <dl v-if="uploadTextual.length" class="metric-tail">
      <div
        v-for="item in uploadTextual"
        :key="`upt-${item.k}`"
        class="metric-tail-row"
      >
        <dt class="metric-tail-k">{{ item.k }}</dt>
        <dd class="metric-tail-v">{{ item.v }}</dd>
      </div>
    </dl>
  </section>

  <!-- 文件树（asmr_sync / pipeline_delete / auto_import / process_existing / subtitle_batch / filter_delete） -->
  <section
    v-for="section in entrySections"
    :key="`es-${section.key}`"
    class="panel"
  >
    <div class="entry-section-head">
      <div class="entry-section-head-copy">
        <div class="entry-eyebrow">{{ entrySectionTitle }}</div>
        <div class="entry-section-title">{{ section.title }}</div>
        <div v-if="section.description" class="entry-section-desc mono">{{ section.description }}</div>
      </div>
      <button
        type="button"
        class="entry-section-toggle"
        @click.stop="m.toggleEntrySection(section.key)"
      >
        {{ m.isEntrySectionExpanded(section.key) ? '收起' : '展开' }}
      </button>
    </div>
    <div
      v-if="m.isEntrySectionExpanded(section.key) && m.flattenEntryRows(section.rows).length"
      class="entry-tree-box"
    >
      <div
        v-for="entry in m.flattenEntryRows(section.rows)"
        :key="`${section.key}-${entry.key}`"
        class="tree-row-shell"
      >
        <div
          class="tree-row"
          :class="{ 'is-expandable': entry.expandable }"
          :style="{ paddingLeft: `${12 + (entry.depth || 0) * 18}px` }"
        >
          <div class="tree-main">
            <button
              v-if="entry.expandable"
              type="button"
              class="tree-inline-toggle"
              :class="{ expanded: m.isEntryTreeRowExpanded(entry.key) }"
              :aria-label="m.isEntryTreeRowExpanded(entry.key) ? '收起' : '展开'"
              @click.stop="m.toggleEntryTreeRow(entry.key)"
            >
              <ChevronRight :size="12" :stroke-width="2.6" />
            </button>
            <span v-else class="tree-expander-spacer" />
            <span
              class="entry-main-target"
              :class="{
                'is-added': entry.variant === 'added',
                'is-changed': entry.variant === 'changed'
              }"
            >
              <div class="entry-main-copy">
                <div class="entry-title-row">
                  <span
                    class="entry-primary-line"
                    :class="{ 'is-deleted': entry.variant === 'deleted' }"
                  >
                    <component
                      :is="m.resolveEntryIcon(entry)"
                      :size="20"
                      :class="['entry-icon', m.entryIconClass(entry), { 'is-deleted': entry.variant === 'deleted' }]"
                    />
                    <span :class="['entry-name', { 'is-deleted': entry.variant === 'deleted', 'is-added': entry.variant === 'added', 'is-changed': entry.variant === 'changed', 'is-failed': entry.variant === 'failed' || entry.variant === 'warning' }]">
                      {{ entry.label || entry.name || entry.relative_path || '—' }}
                    </span>
                  </span>
                  <span
                    v-for="badge in entry.badges || []"
                    :key="`${entry.key}-${badge}`"
                    class="entry-inline-badge"
                  >{{ badge }}</span>
                </div>
                <span v-if="entry.metaText" class="entry-meta-text">{{ entry.metaText }}</span>
              </div>
            </span>
          </div>
          <span v-if="entry.sizeText" class="entry-size">{{ entry.sizeText }}</span>
          <span v-if="entry.error" class="entry-error">{{ entry.error }}</span>
        </div>
      </div>
    </div>
    <div
      v-else-if="m.isEntrySectionExpanded(section.key)"
      class="entry-tree-empty"
    >
      暂无文件树内容
    </div>
  </section>

  <!-- 删除过滤预审：命中文件清单（仅在 entrySections 没有覆盖时显示） -->
  <section
    v-if="filterPreviewItems.length && !entrySections.length"
    class="panel"
  >
    <div class="panel-head">
      <Filter :size="13" :stroke-width="2.4" />
      <span>命中文件</span>
      <span class="panel-head-count">{{ filterPreviewItems.length }}</span>
      <button
        v-if="filterPreviewItems.length > filterItemsLimit"
        class="panel-toggle"
        type="button"
        @click="filterItemsLimit = filterItemsLimit === 8 ? filterPreviewItems.length : 8"
      >
        {{ filterItemsLimit === 8 ? `展开全部` : '收起' }}
      </button>
    </div>
    <ul class="path-list">
      <li
        v-for="(item, idx) in filterPreviewItems.slice(0, filterItemsLimit)"
        :key="`${item.path || item.relative_path || idx}`"
        class="path-item"
      >
        <component
          :is="item.type === 'dir' ? Folder : FileText"
          :size="13"
          :stroke-width="2.4"
          class="path-icon"
        />
        <span class="path-name mono">{{ item.relative_path || item.name || item.path }}</span>
        <span v-if="item.size" class="path-size">{{ formatBytes(item.size) }}</span>
      </li>
    </ul>
  </section>

  <!-- ASMR 同步：上传文件列表（仅在 entrySections 没有覆盖时显示） -->
  <section
    v-if="asmrUploadFiles.length && !entrySections.length"
    class="panel"
  >
    <div class="panel-head">
      <Upload :size="13" :stroke-width="2.4" />
      <span>上传文件</span>
      <span class="panel-head-count">{{ asmrUploadFiles.length }}</span>
      <button
        v-if="asmrUploadFiles.length > asmrUploadLimit"
        class="panel-toggle"
        type="button"
        @click="asmrUploadLimit = asmrUploadLimit === 6 ? asmrUploadFiles.length : 6"
      >
        {{ asmrUploadLimit === 6 ? '展开全部' : '收起' }}
      </button>
    </div>
    <ul class="path-list">
      <li
        v-for="(file, idx) in asmrUploadFiles.slice(0, asmrUploadLimit)"
        :key="`${file.relative_path || file.name || idx}`"
        class="path-item"
      >
        <FileText :size="13" :stroke-width="2.4" class="path-icon" />
        <span class="path-name mono">{{ file.relative_path || file.name || '—' }}</span>
        <span v-if="file.size_bytes || file.size" class="path-size">{{ formatBytes(file.size_bytes || file.size) }}</span>
      </li>
    </ul>
  </section>

  <!-- 解压 / 入库：产物文件树（仅在 entrySections 没有覆盖时显示） -->
  <section
    v-if="extractFileTree.length && !filterPreviewItems.length && !entrySections.length"
    class="panel"
  >
    <div class="panel-head">
      <Folder :size="13" :stroke-width="2.4" />
      <span>解压产物</span>
      <span class="panel-head-count">{{ extractFileTree.length }}</span>
      <button
        v-if="extractFileTree.length > extractLimit"
        class="panel-toggle"
        type="button"
        @click="extractLimit = extractLimit === 8 ? extractFileTree.length : 8"
      >
        {{ extractLimit === 8 ? '展开全部' : '收起' }}
      </button>
    </div>
    <ul class="path-list">
      <li
        v-for="(item, idx) in extractFileTree.slice(0, extractLimit)"
        :key="`${item.path || item.relative_path || idx}`"
        class="path-item"
        :style="{ paddingLeft: `${(item.relative_path || '').split('/').length * 6}px` }"
      >
        <component
          :is="item.type === 'dir' ? Folder : FileText"
          :size="13"
          :stroke-width="2.4"
          class="path-icon"
        />
        <span class="path-name mono">{{ item.relative_path || item.name }}</span>
        <span v-if="item.size" class="path-size">{{ formatBytes(item.size) }}</span>
      </li>
    </ul>
  </section>

  <!-- 社团补全：特典探测结果 -->
  <section v-if="bonusProbe" class="panel bonus-probe-panel" :class="bonusProbe.status === 'hit' ? 'is-hit' : 'is-miss'">
    <div class="panel-head">
      <Sparkles :size="13" :stroke-width="2.4" />
      <span>特典探测结果</span>
      <span
        class="ml-1 inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset"
        :class="bonusProbe.status === 'hit' ? 'bg-slate-50/80 text-slate-700 ring-slate-200/60' : 'bg-slate-50/80 text-slate-500 ring-slate-200/60'"
      >{{ bonusProbe.statusLabel }}</span>
    </div>
    <div class="bonus-probe-summary">
      <div>
        <div class="bonus-probe-source">{{ bonusProbe.sourceLabel }}</div>
        <div class="bonus-probe-title">
          {{ bonusProbe.status === 'hit' ? `找到 ${bonusProbe.items.length} 个特典` : '未找到符合条件的特典' }}
        </div>
      </div>
      <div class="bonus-probe-metrics">
        <span
          v-for="metric in bonusProbe.metrics"
          :key="`bpm-${metric.label}`"
          class="bonus-probe-metric"
        >
          {{ metric.label }}<b>{{ metric.value }}</b>
        </span>
      </div>
    </div>
    <ul v-if="bonusProbe.items.length" class="bonus-work-list">
      <li
        v-for="item in bonusProbe.items"
        :key="`bonus-${item.rjcode}`"
        class="bonus-work-item"
      >
        <div class="bonus-work-head">
          <span class="bonus-work-rj">{{ item.rjcode }}</span>
          <span class="bonus-work-name">{{ item.title || '未命名特典' }}</span>
        </div>
        <div class="bonus-work-meta">
          <span v-if="item.releaseDate">发售日 {{ item.releaseDate }}</span>
          <span v-if="item.makerId">maker {{ item.makerId }}</span>
        </div>
      </li>
    </ul>
    <div v-else class="bonus-probe-empty">
      已完成本次特典筛选，但没有命中隐藏特典条件的 RJ。
    </div>
    <div v-if="bonusProbe.dateRows.length" class="bonus-date-strip">
      <span
        v-for="row in bonusProbe.dateRows.slice(0, 12)"
        :key="`bpdr-${row.releaseDate}`"
        class="bonus-date-pill"
        :class="row.hitCount > 0 ? 'is-hit' : (row.skipped ? 'is-skipped' : '')"
      >
        {{ row.releaseDate || '未知日期' }}
        <b>{{ row.hitCount }}</b>
      </span>
      <span v-if="bonusProbe.dateRows.length > 12" class="bonus-date-more">+{{ bonusProbe.dateRows.length - 12 }}</span>
    </div>
  </section>

  <!-- 社团索引：高级面板（搜索 + 来源过滤 + 来源 breakdown） -->
  <section v-if="circleIndexModel" class="panel">
    <div class="panel-head">
      <Users :size="13" :stroke-width="2.4" />
      <span>社团索引</span>
      <span class="panel-head-count">{{ circleIndexModel.rows.length }}</span>
    </div>
    <p class="text-[11.5px] leading-relaxed text-slate-500 mb-2">{{ circleIndexSummary }}</p>
    <div v-if="circleIndexModel.sourceBreakdown.length" class="flex flex-wrap gap-1.5 mb-2.5">
      <span
        v-for="b in circleIndexModel.sourceBreakdown"
        :key="`cibd-${b.key}`"
        class="inline-flex items-center gap-1 px-2 py-[3px] rounded-[4px] text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60"
      >{{ b.label }}<span class="tabular-nums opacity-70">{{ b.count }}</span></span>
    </div>
    <div class="flex items-center gap-2 flex-wrap mb-2.5">
      <div class="flex-1 min-w-[200px] relative">
        <Search :size="13" :stroke-width="2.4" class="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          v-model="compareSearchQuery"
          type="text"
          placeholder="搜索 RJ / 标题 / Tag..."
          class="w-full pl-7 pr-3 py-1.5 text-[12px] rounded-[6px] bg-white ring-1 ring-inset ring-slate-200/70 focus:ring-slate-300/70 focus:outline-none transition-all placeholder:text-slate-400"
        >
      </div>
      <AppDropdown
        v-model="compareVariantFilter"
        :options="CIRCLE_VARIANT_FILTERS"
        label="版本"
        :width="150"
        :menu-min-width="150"
      />
      <div class="flex flex-wrap gap-1">
        <button
          v-for="f in CIRCLE_SOURCE_FILTERS"
          :key="`cif-${f.value}`"
          type="button"
          class="px-2.5 py-1 rounded-[6px] text-[11px] font-medium tracking-tight transition-all"
          :class="compareSourceFilter === f.value
            ? 'bg-slate-50 text-slate-800 ring-1 ring-inset ring-slate-200/70 shadow-sm'
            : 'text-slate-600 hover:bg-slate-50 ring-1 ring-inset ring-transparent'"
          @click="compareSourceFilter = f.value"
        >{{ f.label }}</button>
      </div>
    </div>
    <ul class="m-0 p-0 list-none flex flex-col gap-1.5 max-h-[480px] overflow-y-auto pr-1">
      <li
        v-for="work in filteredCircleIndexRows"
        :key="`cir-${work.canonical_rjcode || work.workRjcode}`"
        class="px-4.5 py-3.5 rounded-[10px] bg-white ring-1 ring-inset ring-slate-200/40 hover:ring-slate-300/60 hover:shadow-sm transition-all"
      >
        <div class="flex items-center gap-2 flex-wrap mb-1">
          <span class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[11px] font-mono font-semibold tracking-tight bg-slate-100/70 text-slate-700 ring-1 ring-inset ring-slate-200/60">{{ work.display_rjcode || work.workRjcode || work.canonical_rjcode || '—' }}</span>
          <span class="flex-1 min-w-0 truncate text-[12.5px] font-semibold text-slate-800">{{ work.title || '未命名作品' }}</span>
          <span
            v-if="work.statusLabel"
            class="shrink-0 inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset"
            :class="circleFlagClasses(work.statusKey === 'owned' ? 'is-owned' : (work.statusKey === 'missing' ? 'is-missing' : (work.statusKey === 'partial' ? 'is-partial' : '')))"
          >{{ work.statusLabel }}</span>
        </div>
        <div class="flex flex-wrap gap-1">
          <span v-if="work.variantTypeTag" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('info')">{{ work.variantTypeTag }}</span>
          <span v-if="work.isBonusWork" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('warn')">特典</span>
          <span v-if="work.variantTypeTag === '原作'" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses(work.originalSubtitlePresent ? 'success' : 'neutral')">{{ work.originalSubtitlePresent ? '原作字幕' : '原作无字幕' }}</span>
          <span v-if="work.hasSubtitleTag" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('success')">字幕</span>
          <span v-if="work.sourceCompare.kikoeru.primary_rjcode" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('info')">Kikoeru<span v-if="work.sourceCompare.kikoeru.primaryBadge"> · {{ work.sourceCompare.kikoeru.primaryBadge }}</span></span>
          <span v-if="work.sourceCompare.dlsite.all_rjcodes.length" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('warn')">DLsite × {{ work.sourceCompare.dlsite.all_rjcodes.length }}</span>
          <span v-if="work.sourceCompare.asmr_one.primary_rjcode" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('success')">asmr.one<span v-if="work.sourceCompare.asmr_one.primaryBadge"> · {{ work.sourceCompare.asmr_one.primaryBadge }}</span></span>
          <span v-if="!work.sourceCompare.kikoeru.primary_rjcode && !work.sourceCompare.dlsite.all_rjcodes.length && !work.sourceCompare.asmr_one.primary_rjcode" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('neutral')">暂无来源</span>
        </div>
      </li>
    </ul>
    <p v-if="filteredCircleIndexRows.length === 0" class="text-[12px] text-slate-500 text-center py-4">未匹配到作品，调整筛选条件试试。</p>
  </section>

  <!-- 社团补全：作品来源对比（紧凑版，仅在没有高级 circleIndexModel 时显示） -->
  <section
    v-if="circleIndexRows.length && !circleIndexModel"
    class="panel"
  >
    <div class="panel-head">
      <Users :size="13" :stroke-width="2.4" />
      <span>社团作品</span>
      <span class="panel-head-count">{{ circleIndexRows.length }}</span>
      <button
        v-if="circleIndexRows.length > circleIndexLimit"
        class="panel-toggle"
        type="button"
        @click="circleIndexLimit = circleIndexLimit === 8 ? circleIndexRows.length : 8"
      >
        {{ circleIndexLimit === 8 ? '展开全部' : '收起' }}
      </button>
    </div>
    <ul class="circle-list">
      <li
        v-for="(work, idx) in circleIndexRows.slice(0, circleIndexLimit)"
        :key="`${work.workRjcode || work.canonical_rjcode || idx}`"
        class="circle-item"
      >
        <div class="circle-head">
          <span class="inline-flex items-center px-1.5 py-[2px] rounded text-[11px] font-mono font-semibold tracking-tight bg-slate-100/70 text-slate-700 ring-1 ring-inset ring-slate-200/60">{{ work.workRjcode || work.canonical_rjcode || '—' }}</span>
          <span class="circle-title">{{ work.title || '未命名作品' }}</span>
        </div>
        <div class="circle-sources">
          <span v-if="work.kikoeru_primary_rjcode" class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('info')">Kikoeru</span>
          <span v-if="work.dlsite_count" class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('warn')">DLsite × {{ work.dlsite_count }}</span>
          <span v-if="work.asmr_one_primary_rjcode" class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('success')">asmr.one</span>
          <span v-if="!work.kikoeru_primary_rjcode && !work.dlsite_count && !work.asmr_one_primary_rjcode" class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('neutral')">暂无来源</span>
        </div>
      </li>
    </ul>
  </section>

  <!-- 社团补全：刷新结果 -->
  <section
    v-if="circleRefreshModel"
    class="panel"
  >
    <div class="panel-head">
      <RefreshCw :size="13" :stroke-width="2.4" />
      <span>本次刷新</span>
      <span class="panel-head-count">{{ circleRefreshModel.refreshedCount }}</span>
    </div>
    <div class="flex flex-wrap gap-1.5 mb-2.5">
      <span class="inline-flex items-center gap-1 px-2 py-[3px] rounded-[4px] text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60">选中<span class="tabular-nums opacity-70">{{ circleRefreshModel.selectedCount }}</span></span>
      <span class="inline-flex items-center gap-1 px-2 py-[3px] rounded-[4px] text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60">已刷新<span class="tabular-nums opacity-70">{{ circleRefreshModel.refreshedCount }}</span></span>
      <span class="inline-flex items-center gap-1 px-2 py-[3px] rounded-[4px] text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60">有变化<span class="tabular-nums opacity-70">{{ circleRefreshModel.changedCount }}</span></span>
      <span class="inline-flex items-center gap-1 px-2 py-[3px] rounded-[4px] text-[11px] font-semibold tracking-tight bg-slate-50/80 text-slate-700 ring-1 ring-inset ring-slate-200/60">库存已收录<span class="tabular-nums opacity-70">{{ circleRefreshModel.serverMatchedCount }}</span></span>
    </div>
    <div class="flex flex-wrap gap-1 mb-2.5">
      <button
        v-for="f in CIRCLE_REFRESH_FILTERS"
        :key="`crf-${f.value}`"
        type="button"
        class="px-2.5 py-1 rounded-[6px] text-[11px] font-medium tracking-tight transition-all"
        :class="circleRefreshFilter === f.value
          ? 'bg-slate-50 text-slate-800 ring-1 ring-inset ring-slate-200/70 shadow-sm'
          : 'text-slate-600 hover:bg-slate-50 ring-1 ring-inset ring-transparent'"
        @click="setCircleRefreshFilter(f.value)"
      >{{ f.label }}</button>
    </div>
    <ul class="m-0 p-0 list-none flex flex-col gap-1.5 max-h-[480px] overflow-y-auto pr-1">
      <li
        v-for="item in pagedCircleRefreshItems"
        :key="`crfi-${item.canonical_rjcode}`"
        class="px-4.5 py-3.5 rounded-[10px] bg-white ring-1 ring-inset ring-slate-200/40 hover:ring-slate-300/60 hover:shadow-sm transition-all"
      >
        <div class="flex items-center gap-2 flex-wrap mb-1">
          <span class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[11px] font-mono font-semibold tracking-tight bg-slate-100/70 text-slate-700 ring-1 ring-inset ring-slate-200/60">{{ item.display_rjcode || item.canonical_rjcode }}</span>
          <span class="flex-1 min-w-0 truncate text-[12.5px] font-semibold text-slate-800">{{ item.title || '未命名作品' }}</span>
          <span v-if="item.changed" class="shrink-0 inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-bold tracking-wider ring-1 ring-inset" :class="circleFlagClasses('is-new')">NEW</span>
          <span
            class="shrink-0 inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset"
            :class="circleFlagClasses(item.resultStatus === 'owned' ? 'is-owned' : (item.resultStatus === 'missing' ? 'is-missing' : ''))"
          >{{ item.resultLabel }}</span>
        </div>
        <div class="flex flex-wrap gap-1">
          <span v-if="item.preferred_variant_label" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('info')">{{ item.preferred_variant_label }}</span>
          <span v-if="item.subtitlePresent" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-semibold tracking-wide ring-1 ring-inset" :class="srcTagClasses('success')">字幕</span>
          <span v-if="item.serverMatchPrimaryRjcode" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-mono font-semibold tracking-tight ring-1 ring-inset" :class="srcTagClasses('info')">Kikoeru · {{ item.serverMatchPrimaryRjcode }}</span>
          <span v-if="item.asmrAvailableRjcode" class="inline-flex items-center px-1.5 py-[2px] rounded-[4px] text-[10px] font-mono font-semibold tracking-tight ring-1 ring-inset" :class="srcTagClasses('success')">asmr.one · {{ item.asmrAvailableRjcode }}</span>
        </div>
        <ul v-if="item.changeDetails.length" class="m-0 p-0 list-none flex flex-col gap-0.5 mt-1.5 pt-1.5 border-t border-slate-100">
          <li
            v-for="change in item.changeDetails"
            :key="`crfc-${item.canonical_rjcode}-${change.key}`"
            class="flex items-center gap-1.5 text-[11px] text-slate-600 flex-wrap"
          >
            <ArrowRightLeft :size="10" :stroke-width="2.4" class="text-slate-500 shrink-0" />
            <span class="font-semibold text-slate-700 tracking-tight">{{ change.label }}</span>
            <span class="text-slate-400">{{ formatRefreshChangeValue(change.before) }}</span>
            <ChevronRight :size="10" :stroke-width="2.4" class="text-slate-300" />
            <span class="text-slate-700 font-medium">{{ formatRefreshChangeValue(change.after) }}</span>
          </li>
        </ul>
      </li>
    </ul>
    <p v-if="pagedCircleRefreshItems.length === 0" class="text-[12px] text-slate-500 text-center py-4">当前筛选条件下没有结果</p>
    <div
      v-if="circleRefreshModel.items.length > circleRefreshPageSize"
      class="flex items-center justify-between gap-2 mt-2.5 pt-2 border-t border-slate-100"
    >
      <span class="text-[11px] text-slate-500 tabular-nums">第 {{ circleRefreshPage }} / {{ Math.max(1, Math.ceil(circleRefreshModel.items.length / circleRefreshPageSize)) }} 页 · 共 {{ circleRefreshModel.items.length }} 项</span>
      <div class="flex gap-1">
        <button
          type="button"
          class="px-2 py-1 rounded-md text-[11px] font-medium ring-1 ring-inset transition-all"
          :class="circleRefreshPage > 1
            ? 'text-slate-700 bg-white ring-slate-200/70 hover:bg-slate-50'
            : 'text-slate-300 bg-slate-50/50 ring-slate-100 cursor-not-allowed'"
          :disabled="circleRefreshPage <= 1"
          @click="setCircleRefreshPage(circleRefreshPage - 1)"
        >上一页</button>
        <button
          type="button"
          class="px-2 py-1 rounded-md text-[11px] font-medium ring-1 ring-inset transition-all"
          :class="circleRefreshPage < Math.ceil(circleRefreshModel.items.length / circleRefreshPageSize)
            ? 'text-slate-700 bg-white ring-slate-200/70 hover:bg-slate-50'
            : 'text-slate-300 bg-slate-50/50 ring-slate-100 cursor-not-allowed'"
          :disabled="circleRefreshPage >= Math.ceil(circleRefreshModel.items.length / circleRefreshPageSize)"
          @click="setCircleRefreshPage(circleRefreshPage + 1)"
        >下一页</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, toRef } from 'vue'
import { ElButton } from 'element-plus'
import {
  ArrowRightLeft, ArrowUpRight, CheckCircle2, ChevronRight, Clock, FileText,
  ListFilter as Filter, Folder, GitCompareArrows, Image as ImageIcon,
  Layers, Mail, RefreshCw, Search, SlidersHorizontal, Sparkles,
  Upload, Users
} from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'
import { useActivityDetailModels } from '../../composables/useActivityDetailModels'

const props = defineProps({
  row: { type: Object, default: null },
  statusTone: { type: Function, default: () => 'neutral' },
  formatDateTime: { type: Function, default: () => '' },
  compactPath: { type: Function, default: (v) => String(v || '') }
})

const emit = defineEmits(['navigate'])

// 把 row 包成 ref 喂给 composable
const rowRef = toRef(props, 'row')
const m = useActivityDetailModels(rowRef)

// 直接把 composable 的 ref/computed 暴露为顶层名字，模板里直接 auto-unwrap
const highlights = m.highlights
const pathCompare = m.pathCompare
const pathCompareReason = m.pathCompareReason
const pathCompareCls = m.pathCompareCls
const pairWorkbench = m.pairWorkbench
const pairResult = m.pairResult
const showPairWorkbenchPanel = computed(() => Boolean(pairWorkbench.value && (!pairResult.value || pairWorkbench.value.awaiting)))
const subtitleBatchModel = m.subtitleBatchModel
const emailWatcherModel = m.emailWatcherModel
const filterDeleteMetrics = m.filterDeleteMetrics
const uploadMetrics = m.uploadMetrics
const entrySections = m.entrySections
const entrySectionTitle = m.entrySectionTitle

/**
 * 判断 metric 的 v 是不是「数字 + 单位」形式（如 944.41 MB / 3.54 MB/s / 15）。
 * 是 → 走大数字 stat tile；否（路径/库存 ID/中文持续时间）→ 走 footer 行。
 */
function metricSplit(value) {
  const s = String(value ?? '').trim()
  // 纯数字
  if (/^[+-]?\d+(?:\.\d+)?$/.test(s)) return { num: s, unit: '' }
  // 数字 + 英文/百分号/斜杠 单位（MB / GB / KB / MB/s / B 等）
  const m = s.match(/^([+-]?\d{1,3}(?:[,，]?\d{3})*(?:\.\d+)?)\s*([A-Za-z%][A-Za-z%/]*)$/)
  if (m) return { num: m[1], unit: m[2] }
  return { num: s, unit: '' }
}

function isPathLike(value) {
  const s = String(value ?? '').trim()
  if (!s) return false
  // 路径分隔符 → 文本
  if (s.includes('/') || s.includes('\\')) return true
  // 不以数字开头的视为文本（synology / remote-library-3 / 已成功 / 等等）
  if (!/^[+-]?\d/.test(s)) return true
  // 14 字符以上：也走 footer，免得 stat tile 被字撑爆
  if (s.length > 14) return true
  return false
}

function isWideHighlight(value) {
  const s = String(value ?? '').trim()
  return s.length > 34 || s.includes('/') || s.includes('\\')
}

const filterDeleteNumeric = computed(() => filterDeleteMetrics.value.filter((it) => !isPathLike(it.v)))
const filterDeleteTextual = computed(() => filterDeleteMetrics.value.filter((it) => isPathLike(it.v)))
const uploadNumeric = computed(() => uploadMetrics.value.filter((it) => !isPathLike(it.v)))
const uploadTextual = computed(() => uploadMetrics.value.filter((it) => isPathLike(it.v)))

// 批量工作台相关 refs（v-model 需要绑定 ref 本身）
const batchAwaitingOnly = m.batchWorkbenchAwaitingOnly
const selectedBatchKeys = m.selectedBatchWorkbenchKeys
const visibleBatchItems = m.visibleBatchItems
const allBatchSelected = m.allBatchSelected
const selectedBatchItems = m.selectedBatchItems
function selectAwaitingBatch() { m.selectAwaitingBatchItems() }
function toggleAllBatch(checked) { m.toggleAllBatchItems(checked) }

// 社团索引相关 refs / computeds
const circleIndexModel = m.circleIndexModel
const filteredCircleIndexRows = m.filteredCircleIndexRows
const circleIndexSummary = m.circleIndexSummary
const compareSearchQuery = m.compareSearchQuery
const compareSourceFilter = m.compareSourceFilter
const compareVariantFilter = m.compareVariantFilter

// 社团本次刷新相关 refs / computeds
const circleRefreshModel = m.circleRefreshModel
const pagedCircleRefreshItems = m.pagedCircleRefreshItems
const circleRefreshFilter = m.circleRefreshFilter
const circleRefreshPage = m.circleRefreshPage
const circleRefreshPageSize = m.circleRefreshPageSize
const setCircleRefreshFilter = m.setCircleRefreshFilter
const setCircleRefreshPage = m.setCircleRefreshPage
const formatRefreshChangeValue = m.formatRefreshChangeValue
const bonusProbe = m.bonusProbe

const CIRCLE_REFRESH_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'changed', label: '有变化' },
  { value: 'unchanged', label: '无变化' }
]

const CIRCLE_SOURCE_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'kikoeru', label: 'Kikoeru' },
  { value: 'dlsite', label: 'DLsite' },
  { value: 'asmr_one', label: 'asmr.one' }
]

const CIRCLE_VARIANT_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'simp', label: '简体' },
  { value: 'trad', label: '繁体' },
  { value: 'original', label: '原作' },
  { value: 'bonus', label: '特典' },
  { value: 'original_subtitle', label: '原作有字幕' },
  { value: 'original_no_subtitle', label: '原作无字幕' }
]

// 抛出导航事件给父级（ActivityHistory.vue 里再 router.push）
function navigate(action, payload = {}) {
  emit('navigate', { action, row: props.row, ...payload })
}
function openSubtitlePairWorkbench() {
  navigate('subtitle-pair', {
    taskId: m.resolveSubtitleTaskId(props.row),
    folderPath: m.resolveSubtitleFolderPath(props.row),
    libraryId: m.resolveSubtitleLibraryId(props.row)
  })
}
function openSubtitleBatchWorkbench() {
  navigate('subtitle-batch', { items: selectedBatchItems.value })
}
function onEmailWatchCoverError(event, item) {
  m.handleEmailWatchCoverError(event, item)
}

// ===== Tailwind tone 映射 =====
const SRC_TAG_TONE_CLASS = {
  info: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  warn: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  success: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  danger: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  neutral: 'bg-slate-50/80 text-slate-700 ring-slate-200/60'
}

const CIRCLE_FLAG_KIND_CLASS = {
  'is-new': 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  'is-owned': 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  'is-missing': 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  'is-partial': 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  '': 'bg-slate-50/80 text-slate-600 ring-slate-200/60'
}

function srcTagClasses(tone) {
  return SRC_TAG_TONE_CLASS[tone] || SRC_TAG_TONE_CLASS.neutral
}

function circleFlagClasses(kind) {
  return CIRCLE_FLAG_KIND_CLASS[kind] || CIRCLE_FLAG_KIND_CLASS['']
}

const PATH_OP_TAG_CLASS = {
  'is-rename': 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  'is-api-rename': 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  'is-delete': 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  '': 'bg-slate-50/80 text-slate-700 ring-slate-200/60'
}

const PATH_REASON_CLASS = {
  'is-success': 'bg-slate-50/70 text-slate-700 ring-slate-200/50',
  'is-warn': 'bg-slate-50/70 text-slate-700 ring-slate-200/50',
  'is-fail': 'bg-slate-50/70 text-slate-700 ring-slate-200/50'
}

const PAIR_STATUS_CLASS = {
  success: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  warning: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  default: 'bg-slate-50/80 text-slate-600 ring-slate-200/60'
}

const BATCH_STATE_CLASS = {
  success: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  warning: 'bg-slate-50/80 text-slate-700 ring-slate-200/60',
  default: 'bg-slate-50/80 text-slate-600 ring-slate-200/60'
}

function pathOpTagClasses(kind) {
  return PATH_OP_TAG_CLASS[kind] || PATH_OP_TAG_CLASS['']
}

function pathReasonClasses(kind) {
  return PATH_REASON_CLASS[kind] || PATH_REASON_CLASS['is-fail']
}

function pairStatusClasses(status) {
  return PAIR_STATUS_CLASS[status] || PAIR_STATUS_CLASS.default
}

function batchStateClasses(state) {
  return BATCH_STATE_CLASS[state] || BATCH_STATE_CLASS.default
}

const filterItemsLimit = ref(8)
const asmrUploadLimit = ref(6)
const extractLimit = ref(8)
const circleIndexLimit = ref(8)

const detail = computed(() => {
  const d = props.row?.detail
  return d && typeof d === 'object' ? d : {}
})

const category = computed(() => String(props.row?.category || ''))
const action = computed(() => String(props.row?.action || ''))

// ===== 删除过滤 =====
const filterPreviewItems = computed(() => {
  const cat = category.value
  if (cat !== 'pipeline_filter') return []
  const lists = []
  for (const key of ['items', 'succeeded_items', 'failed_items', 'recovered_items', 'attempted_items']) {
    const arr = detail.value[key]
    if (Array.isArray(arr)) lists.push(...arr)
  }
  // 去重 by relative_path
  const seen = new Set()
  const out = []
  for (const it of lists) {
    if (!it || typeof it !== 'object') continue
    const key = String(it.relative_path || it.path || it.name || '').toLowerCase()
    if (key && seen.has(key)) continue
    if (key) seen.add(key)
    out.push(it)
  }
  return out
})

// ===== ASMR upload =====
const asmrUploadFiles = computed(() => {
  if (category.value !== 'asmr_sync' && category.value !== 'upload') return []
  const arr = Array.isArray(detail.value.uploaded_files) ? detail.value.uploaded_files : []
  return arr
})

// ===== 解压产物 =====
const extractFileTree = computed(() => {
  if (!['extract', 'auto_import', 'process_existing'].includes(category.value)) return []
  const arr = Array.isArray(detail.value.file_tree_items) ? detail.value.file_tree_items : []
  // 排序：目录优先，按 relative_path
  return [...arr].sort((a, b) => {
    const aDir = a?.type === 'dir' ? 0 : 1
    const bDir = b?.type === 'dir' ? 0 : 1
    if (aDir !== bDir) return aDir - bDir
    return String(a?.relative_path || '').localeCompare(String(b?.relative_path || ''))
  })
})

// ===== 社团补全 =====
const circleIndexRows = computed(() => {
  if (category.value !== 'circle_completion') return []
  const arr = Array.isArray(detail.value.circle_index_rows) ? detail.value.circle_index_rows : []
  return arr.map(item => ({
    workRjcode: item.workRjcode || item.work_rjcode || item.rjcode || item.canonical_rjcode,
    canonical_rjcode: item.canonical_rjcode,
    title: item.title,
    kikoeru_primary_rjcode: item?.sourceCompare?.kikoeru?.primary_rjcode,
    dlsite_count: Array.isArray(item?.sourceCompare?.dlsite?.all_rjcodes) ? item.sourceCompare.dlsite.all_rjcodes.length : 0,
    asmr_one_primary_rjcode: item?.sourceCompare?.asmr_one?.primary_rjcode
  }))
})

// ===== 工具 =====
function formatBytes(size) {
  const value = Number(size || 0)
  if (!value || value <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = value
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${i === 0 ? Math.round(v) : v.toFixed(2)} ${units[i]}`
}
</script>

<style scoped>
.panel {
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: #ffffff;
  padding: 14px 16px;
  box-shadow: 0 1px 1px rgba(15, 23, 42, 0.02);
}

/* 面板头部：跟文件树 entry-section-head 视觉对齐 */
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: -0.01em;
  text-transform: none;
  color: #1d1d1f;
}

.panel-head > svg {
  color: rgba(15, 23, 42, 0.55);
  flex: 0 0 auto;
}

/* 头部右侧的小计数（如 10、72 等） */
.panel-head-count {
  font-size: 11px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.5);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  margin-left: 2px;
}

.bonus-probe-panel.is-hit {
  border-color: rgba(15, 23, 42, 0.1);
}

.bonus-probe-panel.is-miss {
  background: rgba(248, 250, 252, 0.62);
}

.bonus-probe-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 12px;
}

.bonus-probe-source {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(15, 23, 42, 0.48);
}

.bonus-probe-title {
  margin-top: 3px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.bonus-probe-metrics {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 5px;
}

.bonus-probe-metric,
.bonus-date-pill,
.bonus-date-more {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 23px;
  padding: 0 8px;
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.88);
  color: #475569;
  border: 1px solid rgba(148, 163, 184, 0.22);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.bonus-probe-metric b,
.bonus-date-pill b {
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.bonus-work-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.bonus-work-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.bonus-work-item:hover {
  border-color: rgba(148, 163, 184, 0.34);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
}

.bonus-work-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.bonus-work-rj {
  flex: 0 0 auto;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(241, 245, 249, 0.78);
  color: #334155;
  border: 1px solid rgba(148, 163, 184, 0.2);
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 700;
}

.bonus-work-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1e293b;
  font-size: 13px;
  font-weight: 700;
}

.bonus-work-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 5px;
  color: rgba(15, 23, 42, 0.52);
  font-size: 11.5px;
}

.bonus-probe-empty {
  padding: 14px 12px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px dashed rgba(148, 163, 184, 0.36);
  color: rgba(15, 23, 42, 0.54);
  font-size: 12.5px;
  line-height: 1.55;
}

.bonus-date-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(15, 23, 42, 0.05);
}

.bonus-date-pill.is-hit {
  background: rgba(241, 245, 249, 0.96);
  color: #334155;
  border-color: rgba(100, 116, 139, 0.26);
}

.bonus-date-pill.is-skipped {
  opacity: 0.68;
}

.pair-result-open-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 26px;
  padding: 0 9px;
  border-radius: 8px;
  border: 1px solid rgba(16, 185, 129, 0.24);
  background: rgba(236, 253, 245, 0.78);
  color: #047857;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.pair-result-open-btn svg {
  flex: 0 0 auto;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.pair-result-open-btn:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(16, 185, 129, 0.36);
  background: rgba(209, 250, 229, 0.92);
  box-shadow: 0 8px 18px rgba(16, 185, 129, 0.14);
}

.pair-result-open-btn:hover svg {
  transform: rotate(8deg);
}

.pair-result-open-btn:active {
  transform: scale(0.96);
}

.panel-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 56px;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.8);
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: none;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.panel-toggle:hover {
  background: rgba(248, 250, 252, 0.96);
  color: #334155;
  border-color: rgba(148, 163, 184, 0.32);
}

.pair-metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(152px, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.pair-metric-card {
  min-width: 0;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(248, 250, 252, 0.74);
  padding: 9px 10px;
}

.pair-metric-label {
  font-size: 10.5px;
  font-weight: 700;
  color: rgba(71, 85, 105, 0.74);
  line-height: 1.1;
  white-space: nowrap;
}

.pair-metric-value {
  margin-top: 4px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 800;
  line-height: 1.15;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pair-workbench-card {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(248, 250, 252, 0.82);
}

.pair-workbench-card.is-awaiting {
  border-color: rgba(16, 185, 129, 0.22);
  background: rgba(240, 253, 250, 0.72);
}

.pair-workbench-layout {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.pair-workbench-copy {
  flex: 1 1 260px;
  min-width: 0;
}

.pair-workbench-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(255, 255, 255, 0.72);
  color: #475569;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0;
}

.pair-workbench-title {
  margin-top: 8px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1.25;
}

.pair-workbench-desc {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12.5px;
  line-height: 1.55;
}

.pair-workbench-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.pair-workbench-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(255, 255, 255, 0.76);
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.pair-workbench-button {
  flex: 0 0 auto;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.pair-workbench-button:hover {
  transform: translateY(-2px) scale(1.02);
}

.pair-workbench-button:active {
  transform: scale(0.96);
}

/* ===== 邮件监听新作卡片 =====
   参照邮件 HTML 卡片：方块 + 8px 圆角 + 浅边框 + 极简动效（不要胶囊圆条）
*/
.email-watch-card {
  position: relative;
  border-radius: 8px;
  border: 1px solid #e8ebf0;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.email-watch-card.is-success {
  border-color: rgba(100, 116, 139, 0.26);
}

.email-watch-card.is-failed {
  border-color: rgba(100, 116, 139, 0.3);
}

.email-watch-card:hover {
  transform: translateY(-1px);
  border-color: rgba(15, 23, 42, 0.18);
  box-shadow: 0 6px 16px -10px rgba(15, 23, 42, 0.18);
}

.email-watch-card.is-success:hover {
  border-color: rgba(100, 116, 139, 0.42);
}

.email-watch-card.is-failed:hover {
  border-color: rgba(100, 116, 139, 0.46);
}

.email-watch-cover {
  border-radius: 6px;
  border: 1px solid #e8ebf0;
}

/* 顶部统计 chip（邮件 / 新作 / 成功 / 失败）：方形小标签 */
.email-watch-stat {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.01em;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  white-space: nowrap;
}

.email-watch-stat.is-stat-success {
  background: #f8fafc;
  color: #475569;
  border-color: #e2e8f0;
}

.email-watch-stat.is-stat-failed {
  background: #f8fafc;
  color: #475569;
  border-color: #e2e8f0;
}

/* 邮件主题标签：方形浅蓝小卡 */
.email-watch-subject {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.01em;
  background: #f0f9ff;
  color: #0369a1;
  border: 1px solid #bae6fd;
  white-space: nowrap;
}

/* 卡内 RJ 号：紫色文字（贴合邮件配色） */
.email-watch-rj {
  display: inline-flex;
  align-items: center;
  padding: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: #7b4fb4;
}

/* 状态徽章：方形小色块（不要胶囊） */
.email-watch-status {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid transparent;
  white-space: nowrap;
}

.email-watch-status.is-status-success {
  background: #f1f5f9;
  color: #475569;
  border-color: #e2e8f0;
}

.email-watch-status.is-status-failed {
  background: #f1f5f9;
  color: #475569;
  border-color: #e2e8f0;
}

.email-watch-status.is-status-default {
  background: #f1f5f9;
  color: #475569;
  border-color: #e2e8f0;
}

/* 信息底排 chip：方形小色块，配色对齐邮件 HTML */
.email-watch-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.01em;
  border: 1px solid transparent;
  white-space: nowrap;
}

.email-watch-chip.is-chip-price {
  background: #fff7ed;
  color: #c2410c;
  border-color: #fed7aa;
}

.email-watch-chip.is-chip-type {
  background: #ecfeff;
  color: #0e7490;
  border-color: #a5f3fc;
}

.email-watch-chip.is-chip-index {
  background: #f0f9ff;
  color: #0369a1;
  border-color: #bae6fd;
}

.email-watch-chip.is-chip-backfill-on {
  background: #fefce8;
  color: #b45309;
  border-color: #fde68a;
}

.email-watch-chip.is-chip-backfill-off {
  background: #f8fafc;
  color: #475569;
  border-color: #e2e8f0;
}

/* ===== 文件路径列表 ===== */
.path-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.path-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 8px;
  font-size: 12px;
  transition: background 0.18s ease;
}

.path-item:hover {
  background: rgba(15, 23, 42, 0.03);
}

.path-icon {
  flex-shrink: 0;
  color: rgba(15, 23, 42, 0.45);
}

.path-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1e293b;
}

.path-size {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  color: rgba(15, 23, 42, 0.45);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* ===== 社团列表 ===== */
.circle-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.circle-item {
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(248, 250, 252, 0.5);
}

.circle-item.is-changed {
  background: rgba(52, 199, 89, 0.06);
  border-color: rgba(52, 199, 89, 0.18);
}

.circle-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 4px;
}

/* circle-rj 已迁移到 Tailwind 内联类 */

.circle-title {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.circle-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* src-tag 已迁移到 Tailwind 内联类 */

/* ===== 删除/上传统计：大卡片横向 stat strip ===== */
.metric-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0;
  border-top: 1px solid rgba(15, 23, 42, 0.05);
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
}

.metric-cell {
  position: relative;
  padding: 14px 18px;
  border-right: 1px solid rgba(15, 23, 42, 0.05);
  min-width: 0;
}

.metric-cell:last-child {
  border-right: none;
}

/* 折行换列时：每一行最后一个 cell 也要去掉 border-right；CSS subgrid 不普及，
   退而求其次用一个 :nth 兼容大概，下面交给 break 自己处理 */
@media (max-width: 720px) {
  .metric-cell {
    border-right: none;
    border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  }
  .metric-cell:last-child {
    border-bottom: none;
  }
}

.metric-cell-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(15, 23, 42, 0.5);
  margin-bottom: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-cell-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
}

.metric-num {
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.05;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-unit {
  font-size: 11px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.5);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  flex: 0 0 auto;
}

/* footer 里的「目标路径 / 上传模式 / 库存 ID」等长文本字段 */
.metric-tail {
  margin: 14px 0 0;
  display: grid;
  grid-template-columns: 1fr;
  gap: 0;
}

.metric-tail-row {
  display: grid;
  grid-template-columns: minmax(72px, 96px) 1fr;
  align-items: baseline;
  gap: 14px;
  padding: 8px 4px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
}

.metric-tail-row:last-child {
  border-bottom: none;
}

.metric-tail-k {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.5);
  white-space: nowrap;
}

.metric-tail-v {
  margin: 0;
  font-size: 12.5px;
  font-weight: 500;
  color: #0f172a;
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  line-height: 1.5;
}

/* ===== 关键字段：定义列表 + 细分隔线，告别一个个灰框 ===== */
.highlight-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  column-gap: 28px;
  row-gap: 0;
  margin: 0;
}

.highlight-row {
  display: grid;
  grid-template-columns: minmax(96px, 132px) 1fr;
  align-items: baseline;
  gap: 14px;
  padding: 9px 4px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  transition: background-color 0.18s ease;
}

.highlight-row.is-wide {
  grid-column: 1 / -1;
}

.highlight-row:hover {
  background: rgba(248, 250, 252, 0.55);
}

/* 双列布局时最后一行（含倒数第二行）也去掉底线 */
@media (min-width: 560px) {
  .highlight-row:nth-last-child(-n + 2) {
    border-bottom: none;
  }
}

@media (max-width: 559px) {
  .highlight-row:last-child {
    border-bottom: none;
  }
}

.highlight-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.5);
  text-transform: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.highlight-value {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums;
  word-break: break-all;
  line-height: 1.5;
}

.highlight-value:not(.is-short-value) {
  white-space: normal;
}

/* 关键字段里数字 + 单位拆分（与 metric-strip 同语言但更小） */
.highlight-num {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  line-height: 1;
  white-space: nowrap;
}

.highlight-unit {
  font-size: 10px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.5);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-left: 4px;
  vertical-align: 0.05em;
}

.highlight-row.is-numeric .highlight-value {
  display: inline-flex;
  align-items: baseline;
}

/* ===== 文件树（与原版完全对齐） ===== */
.entry-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.entry-section-head-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.entry-eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: rgba(15, 23, 42, 0.5);
  text-transform: uppercase;
}

.entry-section-title {
  font-size: 13px;
  font-weight: 700;
  color: #1d1d1f;
  letter-spacing: -0.01em;
}

.entry-section-desc {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.46);
  line-height: 1.45;
  word-break: break-all;
}

.entry-section-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 56px;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.8);
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.entry-section-toggle:hover {
  background: rgba(248, 250, 252, 0.96);
  color: #334155;
  border-color: rgba(148, 163, 184, 0.32);
}

:global(html.kikoerumanager-dark) .panel {
  border-color: rgba(255, 255, 255, 0.08);
  background: #111216;
  background-image: none;
  color: #f4f4f5;
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .panel-head,
:global(html.kikoerumanager-dark) .entry-section-head {
  border-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark) .panel-head,
:global(html.kikoerumanager-dark) .panel-head > svg,
:global(html.kikoerumanager-dark) .entry-section-title,
:global(html.kikoerumanager-dark) .highlight-value,
:global(html.kikoerumanager-dark) .highlight-num {
  color: #f4f4f5;
}

:global(html.kikoerumanager-dark) .panel-head-count,
:global(html.kikoerumanager-dark) .entry-eyebrow,
:global(html.kikoerumanager-dark) .entry-section-desc,
:global(html.kikoerumanager-dark) .highlight-label,
:global(html.kikoerumanager-dark) .highlight-unit,
:global(html.kikoerumanager-dark) .bonus-probe-source,
:global(html.kikoerumanager-dark) .bonus-work-meta {
  color: rgba(212, 212, 216, 0.66);
}

:global(html.kikoerumanager-dark) .bonus-probe-panel.is-miss,
:global(html.kikoerumanager-dark) .bonus-work-item,
:global(html.kikoerumanager-dark) .bonus-probe-empty {
  border-color: rgba(255, 255, 255, 0.08);
  background: #17181d;
}

:global(html.kikoerumanager-dark) .bonus-probe-title,
:global(html.kikoerumanager-dark) .bonus-work-name,
:global(html.kikoerumanager-dark) .bonus-probe-metric b,
:global(html.kikoerumanager-dark) .bonus-date-pill b {
  color: #f4f4f5;
}

:global(html.kikoerumanager-dark) .bonus-probe-metric,
:global(html.kikoerumanager-dark) .bonus-date-pill,
:global(html.kikoerumanager-dark) .bonus-date-more,
:global(html.kikoerumanager-dark) .bonus-work-rj {
  border-color: rgba(255, 255, 255, 0.12);
  background: #202126;
  color: #d7dde7;
}

:global(html.kikoerumanager-dark) .bonus-probe-empty {
  color: rgba(212, 212, 216, 0.68);
}

:global(html.kikoerumanager-dark) .bonus-date-strip {
  border-top-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark) .highlight-row {
  border-bottom-color: rgba(255, 255, 255, 0.08);
}

:global(html.kikoerumanager-dark) .highlight-row:hover,
:global(html.kikoerumanager-dark) .tree-row:hover {
  background: #17181d;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-metric-card),
:global(html.dark .activity-detail-panel .pair-metric-card),
:global(html.kikoerumanager-dark) .pair-metric-card,
:global(html.dark) .pair-metric-card {
  border-color: rgba(255, 255, 255, 0.12) !important;
  background: #17181d !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-metric-label),
:global(html.dark .activity-detail-panel .pair-metric-label),
:global(html.kikoerumanager-dark) .pair-metric-label,
:global(html.dark) .pair-metric-label {
  color: rgba(212, 212, 216, 0.66) !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-metric-value),
:global(html.dark .activity-detail-panel .pair-metric-value),
:global(html.kikoerumanager-dark) .pair-metric-value,
:global(html.dark) .pair-metric-value {
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-workbench-card),
:global(html.dark .activity-detail-panel .pair-workbench-card),
:global(html.kikoerumanager-dark) .pair-workbench-card,
:global(html.dark) .pair-workbench-card {
  border-color: rgba(255, 255, 255, 0.12) !important;
  background: #111216 !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-workbench-card.is-awaiting),
:global(html.dark .activity-detail-panel .pair-workbench-card.is-awaiting),
:global(html.kikoerumanager-dark) .pair-workbench-card.is-awaiting,
:global(html.dark) .pair-workbench-card.is-awaiting {
  border-color: rgba(16, 185, 129, 0.28) !important;
  background: #101714 !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-workbench-title),
:global(html.dark .activity-detail-panel .pair-workbench-title),
:global(html.kikoerumanager-dark) .pair-workbench-title,
:global(html.dark) .pair-workbench-title {
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-workbench-desc),
:global(html.dark .activity-detail-panel .pair-workbench-desc),
:global(html.kikoerumanager-dark) .pair-workbench-desc,
:global(html.dark) .pair-workbench-desc {
  color: rgba(212, 212, 216, 0.72) !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-workbench-badge),
:global(html.dark .activity-detail-panel .pair-workbench-badge),
:global(html.kikoerumanager-dark .activity-detail-panel .pair-workbench-chip),
:global(html.dark .activity-detail-panel .pair-workbench-chip),
:global(html.kikoerumanager-dark) .pair-workbench-badge,
:global(html.dark) .pair-workbench-badge,
:global(html.kikoerumanager-dark) .pair-workbench-chip,
:global(html.dark) .pair-workbench-chip {
  border-color: rgba(255, 255, 255, 0.12) !important;
  background: #202126 !important;
  color: #d7dde7 !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-result-open-btn),
:global(html.dark .activity-detail-panel .pair-result-open-btn),
:global(html.kikoerumanager-dark) .pair-result-open-btn,
:global(html.dark) .pair-result-open-btn {
  border-color: rgba(16, 185, 129, 0.3) !important;
  background: rgba(16, 185, 129, 0.12) !important;
  color: #86efac !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .pair-result-open-btn:hover),
:global(html.dark .activity-detail-panel .pair-result-open-btn:hover),
:global(html.kikoerumanager-dark) .pair-result-open-btn:hover,
:global(html.dark) .pair-result-open-btn:hover {
  border-color: rgba(16, 185, 129, 0.42) !important;
  background: rgba(16, 185, 129, 0.18) !important;
}

:global(html.kikoerumanager-dark) .panel-toggle,
:global(html.kikoerumanager-dark) .entry-section-toggle,
:global(html.kikoerumanager-dark) .tree-inline-toggle:hover {
  border-color: rgba(255, 255, 255, 0.12);
  background: #202126;
  background-image: none;
  color: #d7dde7;
}

:global(html.kikoerumanager-dark) .panel-toggle:hover,
:global(html.kikoerumanager-dark) .entry-section-toggle:hover {
  border-color: rgba(255, 255, 255, 0.18);
  background: #2b2c31;
  color: #f4f4f5;
}

:global(html.kikoerumanager-dark) .tree-row:hover {
  border-color: rgba(255, 255, 255, 0.12);
}

:global(html.kikoerumanager-dark .activity-detail-panel .entry-tree-box) {
  scrollbar-color: rgba(113, 113, 122, 0.82) transparent;
}

:global(html.kikoerumanager-dark .activity-detail-panel .tree-row) {
  border-color: rgba(255, 255, 255, 0.08) !important;
  background: #17181d !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .tree-row:hover) {
  border-color: rgba(148, 163, 184, 0.42) !important;
  background: #202126 !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .entry-name),
:global(html.kikoerumanager-dark .activity-detail-panel .entry-name.is-added),
:global(html.kikoerumanager-dark .activity-detail-panel .entry-name.is-changed),
:global(html.kikoerumanager-dark .activity-detail-panel .entry-name.is-failed) {
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .entry-meta-text),
:global(html.kikoerumanager-dark .activity-detail-panel .entry-size) {
  color: rgba(212, 212, 216, 0.74) !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .entry-inline-badge) {
  border-color: rgba(96, 165, 250, 0.28) !important;
  background: rgba(30, 64, 175, 0.26) !important;
  color: #bfdbfe !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .entry-icon.is-file),
:global(html.kikoerumanager-dark .activity-detail-panel .entry-icon.is-text) {
  color: #a1a1aa !important;
}

:global(html.kikoerumanager-dark .activity-detail-panel .entry-icon.is-video),
:global(html.kikoerumanager-dark .activity-detail-panel .entry-icon.is-audio-blue),
:global(html.kikoerumanager-dark .activity-detail-panel .entry-icon.is-audio-purple) {
  color: #93c5fd !important;
}

.entry-tree-box {
  max-height: 360px;
  overflow: auto;
  overflow-x: hidden;
  padding: 0 8px 0 0;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.65) transparent;
}

.entry-tree-empty {
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.4);
}

.tree-row-shell {
  margin-bottom: 4px;
}

.tree-row-shell:last-child {
  margin-bottom: 0;
}

.tree-row {
  display: flex;
  min-height: 32px;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  padding: 6px 10px 6px 12px;
  transition: background-color 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}

.tree-row:hover {
  border-color: rgba(186, 230, 253, 0.7);
  background: rgba(240, 249, 255, 0.45);
}

.tree-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.tree-inline-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #38bdf8;
  flex: 0 0 20px;
  cursor: pointer;
  position: relative;
  z-index: 2;
  transition: background-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.tree-inline-toggle:hover {
  transform: scale(1.08);
  background: rgba(224, 242, 254, 0.76);
  color: #0284c7;
}

.tree-inline-toggle.expanded svg {
  transform: rotate(90deg);
}

.tree-inline-toggle svg {
  transition: transform 0.18s ease;
}

.tree-expander-spacer {
  width: 20px;
  flex: 0 0 20px;
}

.entry-main-target {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  flex: 1;
}

/* 删除项的中划线只覆盖图标到文件名，不扫过大小列。 */
.entry-primary-line.is-deleted::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  border-top: 1.5px solid rgba(148, 163, 184, 0.88);
  transform: translateY(-50%);
  pointer-events: none;
}

.entry-main-target.is-added {
  background: transparent;
}

.entry-main-target.is-changed {
  border-radius: 8px;
  background: linear-gradient(90deg, rgba(239, 246, 255, 0.9), rgba(255, 255, 255, 0));
}

.entry-primary-line {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  flex: 0 1 auto;
}

.entry-icon {
  flex: 0 0 auto;
}

.entry-icon.is-dir {
  color: #f6b73c;
  fill: rgba(251, 191, 36, 0.22);
}

.entry-icon.is-success {
  color: #64748b;
}

.entry-icon.is-added {
  color: #64748b;
  filter: none;
}

.entry-icon.is-changed {
  color: #2563eb;
  filter: drop-shadow(0 6px 12px rgba(37, 99, 235, 0.16));
}

.entry-icon.is-warning {
  color: #64748b;
}

.entry-icon.is-file {
  color: #94a3b8;
}

.entry-icon.is-deleted {
  color: #94a3b8;
  fill: rgba(148, 163, 184, 0.14);
  stroke: #94a3b8;
  opacity: 0.88;
}

.entry-icon.is-audio-blue {
  color: #2563eb;
}

.entry-icon.is-audio-purple {
  color: #7c3aed;
}

.entry-icon.is-image {
  color: #f97316;
}

.entry-icon.is-video {
  color: #6366f1;
}

.entry-icon.is-pdf {
  color: #dc2626;
}

.entry-icon.is-archive {
  color: #d97706;
}

.entry-icon.is-text {
  color: #64748b;
}

.entry-main-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.entry-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-wrap: nowrap;
}

.entry-name {
  min-width: 0;
  color: #1d1d1f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
}

.entry-name.is-deleted {
  color: rgba(29, 29, 31, 0.5);
}

.entry-name.is-added {
  color: #334155;
  font-weight: 700;
}

.entry-name.is-changed {
  color: #334155;
  font-weight: 700;
}

.entry-name.is-failed {
  color: #334155;
}

.entry-meta-text {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.48);
  line-height: 1.4;
  word-break: break-word;
}

/* 上传成功 / 上传中 等内联状态徽标 */
.entry-inline-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid rgba(100, 116, 139, 0.18);
  background: rgba(248, 250, 252, 0.92);
  color: #475569;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
  line-height: 1;
  white-space: nowrap;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.entry-size {
  flex: 0 0 auto;
  min-width: 72px;
  margin-left: 16px;
  color: rgb(148, 163, 184);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  text-align: right;
}

.entry-error {
  flex: 0 0 100%;
  color: #475569;
  font-size: 12px;
  word-break: break-word;
  padding-left: 56px;
}

@media (max-width: 640px) {
  .panel {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    overflow: hidden;
  }
  .entry-section-head {
    align-items: flex-start;
    gap: 8px;
  }
  .entry-section-head-copy,
  .entry-section-title,
  .entry-section-desc {
    min-width: 0;
    max-width: 100%;
  }
  .highlight-grid,
  .highlight-row,
  .metric-strip,
  .metric-tail,
  .path-list,
  .entry-tree-box {
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }
  .highlight-row,
  .metric-tail-row {
    grid-template-columns: 1fr;
    gap: 4px;
    padding: 8px 2px;
  }
  .highlight-label,
  .metric-tail-k {
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
  }
  .highlight-value,
  .metric-tail-v,
  .entry-section-desc {
    min-width: 0;
    max-width: 100%;
    word-break: break-all;
    overflow-wrap: anywhere;
  }
  .metric-cell {
    min-width: 0;
    padding: 10px;
  }
  .bonus-probe-summary {
    flex-direction: column;
    align-items: stretch;
  }
  .bonus-probe-metrics {
    justify-content: flex-start;
  }
  .bonus-work-head {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .bonus-work-name {
    flex: 1 1 100%;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .metric-num {
    font-size: 18px;
  }
  .entry-tree-box {
    max-height: 300px;
    overflow-x: hidden;
    padding-right: 0;
  }
  .tree-row {
    align-items: flex-start;
    gap: 8px;
    padding: 7px 8px;
  }
  .tree-main,
  .entry-main-target,
  .entry-main-copy,
  .entry-title-row {
    min-width: 0;
    max-width: 100%;
  }
  .entry-title-row {
    flex-wrap: wrap;
  }
  .entry-name {
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .entry-size {
    flex: 1 1 100%;
    min-width: 0;
    margin-left: 28px;
    text-align: left;
  }
  .entry-error {
    padding-left: 28px;
  }
  .path-item {
    min-width: 0;
    align-items: flex-start;
  }
  .path-name {
    min-width: 0;
    white-space: normal;
    word-break: break-all;
    overflow-wrap: anywhere;
  }
  .email-watch-card {
    flex-direction: column;
    gap: 10px;
  }
  .email-watch-cover {
    width: 100% !important;
    height: auto !important;
    aspect-ratio: 4 / 3;
  }
  .email-watch-subject {
    max-width: 100%;
    white-space: normal;
    word-break: break-word;
  }
}
</style>
