这些图标用于 AI 字幕配对设置页的模型平台标识。平台优先由模型 ID 解析，例如 `openai/gpt-4o-mini` 固定显示 OpenAI，不受 Base URL 中转站影响。

- openai.svg: Iconify simple-icons:openai
- anthropic.svg: cdn.simpleicons.org/anthropic
- google.svg: cdn.simpleicons.org/google
- deepseek.svg: cdn.simpleicons.org/deepseek
- openrouter.svg: cdn.simpleicons.org/openrouter
- azure.svg: Iconify simple-icons:microsoftazure
- mistral.svg: Iconify simple-icons:mistralai
- ollama.svg: Iconify simple-icons:ollama
- alibabacloud.svg: Iconify simple-icons:alibabacloud
- x.svg: Iconify simple-icons:x
- perplexity.svg: Iconify simple-icons:perplexity

没有稳定本地图标的已知平台会由后端按模型平台官网抓取 favicon 并缓存到 `data/cache/ai_provider_icons`；未知平台才按 Base URL 抓取。
