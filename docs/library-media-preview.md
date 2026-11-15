# 库存媒体预览

图片区域支持滚轮向上放大、向下缩小，范围为适应窗口的 1 倍到 8 倍。`libraryMediaZoom.js` 扩展官方 zoom 插件，复用其缩放、拖动与边界计算，按动画帧合并滚轮事件，兼容像素、行和页滚动单位；不接管缩略图栏、视频和 PDF 的滚动。关闭时移除监听并取消待执行帧。

官方 rotate 3.0.0 在首个 `beforeSlide` 前关闭时，旋转状态尚未建立却被关闭方法读取；`frontend/src/utils/libraryMediaRotate.js` 仅修正该状态判断，尚未展示的图片按未旋转处理，保留官方旋转功能。

实例生命周期由 `frontend/src/utils/libraryMediaGallery.js` 管理。程序关闭只调用一次 `destroy()` 并等待其返回的异步销毁时长；用户关闭时，等 `lgAfterClose` 回调结束、官方 `lgOpened` 复位后再销毁。快速重开等待旧实例释放，只处理最后一次打开，避免旧实例回调销毁新实例、插件重复清理和监听器残留。关闭页面也取消尚未执行的打开。

`node tools/check-gallery-opening.mjs` 同时验证 10 轮关闭中快速重开、最终 DOM 清理与取消打开，捕获插件初始化/销毁警告和浏览器异常。LightGallery 默认测试授权提示属于授权配置，缩略图的浏览器 lazy-load 提示属于正常延迟加载提示；均不能单独作为性能故障证据。

首图加载完成后，使用限定在 `km-media-gallery` 内的 180ms 透明度淡入；切图只使用官方滑动，避免叠加淡入导致画面忽隐忽现。系统开启减少动态效果时关闭首图淡入。样式位于 `frontend/src/styles/library-media-preview.css`。

切图动画为 240ms。官方默认在动画时长加 50ms 后才加载未预载目标，当前通过 `lgBeforeSlide` 后的微任务调用官方 `loadContent(index, false)`，在目标 DOM 和 index 更新后立即启动图片加载，保留原有相邻预加载和虚拟化窗口；视频和 PDF 不使用该提前加载路径。浏览器脚本验证远距离跳图、相邻切图和返回切图，并检查没有重复首图淡入。

动态入口使用 `LIGHT_GALLERY_OPEN_OPTIONS` 关闭来源图片放大和首图缩放开场，将遮罩时长从默认 300ms 缩短到 80ms。LightGallery 会按遮罩时长延迟首图完成态，因此默认配置即使图片已缓存，也存在约 310ms 的首图等待。保留切图动画与官方插件。

`node tools/check-gallery-opening.mjs` 使用 Edge 无头浏览器、100 张图片清单和内存 JPEG 对照默认开场与当前配置，检查首图完成态与视口可见态。该测试隔离网络因素，测量的是插件开场等待，不代表真实库存原图下载耗时。

本地库存图片和视频使用 LightGallery 3。图片使用官方缩放、全屏、缩略图和旋转插件；视频使用官方 video 插件。PDF 统一使用独立的 EmbedPDF 阅读器，本地与 FileStation 库存共用原有预览 API。

HTML5 视频项由 `frontend/src/utils/libraryMediaPreview.js` 构造。媒体地址只放在 `video.source[].src`，下载地址另放 `downloadUrl`，不要设置顶层 `src`：当前 LightGallery 3.0.0 在顶层有 `src` 时按 URL 识别媒体，会把预览 API 误判为图片，显示内容加载失败。

不统一指定 `video/mp4`，由现有预览接口的响应 Content-Type 和浏览器判断格式；插件不会增加浏览器本身不支持的视频编码。

回归测试 `frontend/src/utils/libraryMediaPreview.test.js` 使用真实 LightGallery 与 video 插件，验证 MP4/WebM 预览 API 地址生成 HTML5 video/source 而不是 img，并保留下载地址。DOM 测试不代替真实文件解码验收。

PDF 阅读入口为 `frontend/src/components/library/LibraryPdfReader.vue`，使用 EmbedPDF 2.15.1 的 Vue 阅读器与 PDFium Worker，支持中文工具栏、缩放、分页、搜索、缩略图和文本选择。阅读器独立居中展示，桌面最大 1120 × 820px，左右至少留 32px、上下至少留 40px；手机四周留 12px。不再经过媒体预览的标题栏和边框。阅读器自身四边与四角支持 Pointer Events 拖动缩放，对边保持固定；最小尺寸为 480 × 320px（小视口以可用空间为限），四周至少保留 12px，浏览器缩小时自动收回可见区域。缩放事件按动画帧合并，只改变视口尺寸，不重新创建 PDF 引擎；顶部官方文档标签栏的空白区与文件名可按住拖动整个窗口，关闭和新增文件按钮保留原交互；拖动保持尺寸并限制在可见区域。关闭时释放指针捕获和监听。当前版本提供容器式阅读器，没有独立顶层弹窗 API；启用官方文档标签栏，最后一个文档关闭时退出阅读界面；顶部右上角另有固定的 × 按钮，可直接关闭整个阅读窗口，标签栏预留按钮空间，保留拖动和原有标签关闭行为。Escape 优先关闭阅读器内部对话框和菜单，再退出浏览器全屏或阅读界面；组件卸载时解除事件订阅、释放引擎与 Worker，并恢复原焦点。主题跟随 `useTheme`，切换主题不重新加载文档。WASM 和中日文替代字体由 Vite 输出到本地静态资源，按需加载；关闭默认 Google Fonts 与印章 CDN 请求。Blob Worker 接收的 WASM、文档 URL 必须转成绝对地址，文档请求携带登录 cookie。

文本入口为 `frontend/src/components/library/LibraryTextReader.vue`。预览 API 增加 `raw=true`，在现有库存路径权限、类型白名单和 12 MiB 限制内返回原始字节，本地和 FileStation 使用同一协议；不带该参数时保留原来的 UTF-8 转码响应。前端优先识别 BOM、严格验证 UTF-8，其余文本通过 jschardet 检测前 64 KiB 样本，再用 TextDecoder 对完整内容应用检测结果。统计识别显示编码、置信度，低置信度提示核对；自动识别并不保证所有短文本均可准确判定。

编码可以手动切换，直接重解码内存中的原始字节，不重复下载。支持 UTF-8、Shift-JIS/CP932、EUC-JP、ISO-2022-JP、GB18030/GBK、Big5、UTF-16 LE/BE、EUC-KR 和 Windows-1252。编码选择按库存 ID 与文件路径保存在当前浏览器，最多记忆 100 个文件；字体和字号为阅读器全局偏好。切换文件、关闭时取消未完成请求，旧响应不能覆盖当前文档。

文本默认使用 17px 黑体、1.95 倍行高、88ch 最大行宽，支持宋体/等宽字体及 14–28px 字号，保留原有换行并自动折长行。浅色使用实色阅读背景，暗色跟随系统主题；移动端压缩工具栏和页边距。正文始终使用 Vue 文本插值，HTML 标签不会执行。

`node tools/check-library-readers.mjs` 用 Edge 实测日文旧编码的自动解码、手动切换、刷新后的编码/字号记忆、移动端暗色排版，以及真实 PDFium 渲染、主题切换、连续关闭重开和无外部 CDN 请求；结果截图保存到 `data/reader-validation/`。此验证使用本地样本，不代表生产 FileStation 实际文件验收。
