# vc_official —— 官方 VideoCaptioner 实现归档（v1.11.0 套用源）

来源：`E:\VideoCaptioner`（官方 VideoCaptioner 安装版，
`app\core\subtitle_processor\translate.py` / `prompt.py`）。
提取日期：2026-09-13。套用入口：`src\apply_vc_official.py`（幂等，覆盖前自动备份）。

## 本目录内容

| 文件 | 覆盖目标（tools\python\...\videocaptioner\） | 说明 |
| --- | --- | --- |
| `translate_standard.md` | `core\prompts\translate\standard.md` | 官方 LLM 翻译提示词 |
| `translate_reflect.md` | `core\prompts\translate\reflect.md` | 官方反思翻译提示词 |
| `translate_single.md` | `core\prompts\translate\single.md` | 官方单条翻译提示词 |
| `optimize_subtitle.md` | `core\prompts\optimize\subtitle.md` | 官方字幕优化提示词 |
| `split_semantic.md` | `core\prompts\split\semantic.md` | 官方语义分段提示词 |
| `split_sentence.md` | `core\prompts\split\sentence.md` | 官方句子分段提示词 |
| `analysis_video.md` | `core\prompts\analysis\video.md` | 官方视频分析提示词 |
| `google_translator.py` | `core\translate\google_translator.py` | 官方谷歌翻译（http 端点 + lang_map + ERROR 标记） |
| `bing_translator.py` | `core\translate\bing_translator.py` | 官方必应翻译（端点与官方一致） |
| `deeplx_translator.py` | `core\translate\deeplx_translator.py` | 官方 DeepLX 翻译 |
| `subtitle_thread.py` | `ui\thread\subtitle_thread.py` | 官方字幕线程 + v1.11.0 取消修复（stop() 补停翻译器线程池） |

## 为什么必须归档

`tools\python` 属于运行时依赖，重装/重下后这些改动会丢失；本目录是
**可复现的源**，重装后执行一次 `python src\apply_vc_official.py` 即可恢复。

## 已知事实（2026-09-13 实测）

- 微软翻译取 token 端点 `edge.microsoft.com/translate/auth` 已 404（官方新版
  同端点同样失效）；谷歌 `translate.google.com` 在国内网络直连超时；官方
  「软件公益模型」`ddg.bkfeng.top` 域名已 NXDOMAIN 下线。
  → 免费翻译服务不可用是端点侧问题，照抄官方实现只能保证行为一致。
- 真正的可用性由 `engine.vc_translate_fallback_patch()` 两段兜底保证：
  创建失败 / 整篇无有效译文（ERROR 类）→ 自动改用 LLM 翻译，日志见
  `logs\vc_fallback.log`；并发压到 `_LLM_THREAD_CAP=5` 防 429 刷屏；
  「启用 AI」关闭时兜底绝不介入。
