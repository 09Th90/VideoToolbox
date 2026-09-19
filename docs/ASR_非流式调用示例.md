<!-- @version 1.15.1 -->
# ASR 非流式调用示例（curl / Python）

> 本文由 `engine.asr_examples()` 生成，与程序内 `_asr_*_submit` 的实现
> **一一对应**：同一个端点、同样的鉴权头与 body 形态。
> 因此「用下面的 curl 跑通」等价于「这套密钥 / 地址 / 模型可用」。
>
> 三点通用约定：
> 1. **非流式**：一次请求（或"上传 → 提交 → 轮询"）返回完整结果，不是 WebSocket 实时流；
> 2. **实时模型用不了**（名字里带 `realtime` / `-rt-` / `streaming` 的），程序会提前拦下并提示替代型号；
> 3. 密钥一律用环境变量占位，示例里不出现明文。

## 常见服务填法速查

| 服务 | 「接口地址」填什么 | 模型名 | 协议（留自动识别即可） |
|---|---|---|---|
| 智谱 GLM-ASR | `https://open.bigmodel.cn/api/paas/v4` | `glm-asr-2512` | openai 兼容 |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `FunAudioLLM/SenseVoiceSmall` | openai 兼容 |
| OpenAI | `https://api.openai.com/v1` | `whisper-1` | openai 兼容 |
| Groq / Fireworks / DeepInfra | `https://api.groq.com/openai/v1` 等 | `whisper-large-v3` 等 | openai 兼容 |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3-asr-flash` | 阿里百炼 |
| 阿里云百炼实时 | `https://dashscope.aliyuncs.com`（实例域名同理，自动换 wss） | `fun-asr-flash-8k-realtime`、`fun-asr-realtime`、`qwen3-asr-flash-realtime` | 百炼实时（WebSocket） |
| 火山（豆包）极速版 | `https://openspeech.bytedance.com` | `volc.bigasr.auc_turbo` | 火山 |
| Deepgram | `https://api.deepgram.com` | `nova-3` | Deepgram |
| ElevenLabs | `https://api.elevenlabs.io` | `scribe_v1` | ElevenLabs |
| AssemblyAI | `https://api.assemblyai.com` | `universal-3-pro,universal-2` | AssemblyAI |
| Google Gemini | `https://generativelanguage.googleapis.com` | `gemini-2.5-flash` | Gemini |
| Azure OpenAI | `https://<资源名>.openai.azure.com` | 部署名 | Azure |

**地址可以填"完整端点"**：像 `https://open.bigmodel.cn/api/paas/v4/audio/transcriptions`
这种直接从文档抄来的完整 URL 也能用——程序会自动削掉多出来的路径段，
不会拼成 `.../audio/transcriptions/audio/transcriptions`。

> ⚠️ 智谱 GLM-ASR-2512 目前定位**短音频**（官方示例按 ≤30s / ≤25MB 给），
> 长视频建议改用百炼 `qwen3-asr-flash`、硅基流动 SenseVoice 或本地
> faster-whisper 模型。另外它返回的是纯文本、不带时间轴，本程序会按句切分
> 后再按句长占比给出近似时间轴。

## OpenAI Whisper 兼容（协议 `openai`）
**先设环境变量**：`ASR_API_KEY` → 设置页「ASR 密钥」里填的那个
### curl（非流式）

```bash
curl -X POST "https://api.siliconflow.cn/v1/audio/transcriptions" \
  -H "Authorization: Bearer $ASR_API_KEY" \
  -F "file=@audio.mp3" \
  -F "model=FunAudioLLM/SenseVoiceSmall" \
  -F "response_format=verbose_json" \
  -F "timestamp_granularities[]=word"
```

### Python（非流式）

```python
import os
from openai import OpenAI

client = OpenAI(base_url='https://api.siliconflow.cn/v1', api_key=os.environ["ASR_API_KEY"])
with open("audio.mp3", "rb") as f:
    r = client.audio.transcriptions.create(
        model='FunAudioLLM/SenseVoiceSmall', file=f, response_format="verbose_json",  # 非流式
        timestamp_granularities=["word"])
print(r.text)
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

## Azure OpenAI（协议 `azure`）
**先设环境变量**：`ASR_API_KEY` → 设置页「ASR 密钥」里填的那个
### curl（非流式）

```bash
curl -X POST "https://<你的资源名>.openai.azure.com/openai/deployments/whisper/audio/transcriptions?api-version=2024-10-21" \
  -H "api-key: $ASR_API_KEY" \
  -F "file=@audio.mp3" \
  -F "response_format=verbose_json"
```

### Python（非流式）

```python
import os
from openai import AzureOpenAI

client = AzureOpenAI(azure_endpoint='https://<你的资源名>.openai.azure.com', api_key=os.environ["ASR_API_KEY"],
                       api_version="2024-10-21")
with open("audio.mp3", "rb") as f:
    r = client.audio.transcriptions.create(
        model='whisper', file=f, response_format="verbose_json")   # 非流式
print(r.text)
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

## Chat 音频转写（百炼 Qwen-ASR / 小米 MiMo 等）（协议 `chat_audio`）
**先设环境变量**：`ASR_API_KEY` → 设置页「ASR 密钥」里填的那个
### curl（非流式）

```bash
BODY=$(python -c "import base64,json;b=base64.b64encode(open('audio.mp3','rb').read()).decode();print(json.dumps({'model':'qwen3-asr-flash','messages':[{'role':'user','content':[{'type':'input_audio','input_audio':{'data':'data:audio/mp3;base64,'+b}}]}],'stream':False}))")
curl -X POST "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions" \
  -H "Authorization: Bearer $ASR_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

### Python（非流式）

```python
import base64, os
from openai import OpenAI

client = OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', api_key=os.environ["ASR_API_KEY"])
b64 = base64.b64encode(open("audio.mp3", "rb").read()).decode()
r = client.chat.completions.create(          # 非流式
    model='qwen3-asr-flash',
    messages=[{"role": "user", "content": [
        {"type": "input_audio",
         "input_audio": {"data": "data:audio/mp3;base64," + b64}}]}],
    stream=False)
print(r.choices[0].message.content)
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

> 音频走 input_audio 的 **Data URL**（自带 MIME）；`stream=false` 才是非流式。

## Deepgram（协议 `deepgram`）
**先设环境变量**：`ASR_API_KEY` → 设置页「ASR 密钥」里填的那个
### curl（非流式）

```bash
curl -X POST "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language=zh-CN" \
  -H "Authorization: Token $ASR_API_KEY" \
  -H "Content-Type: audio/mp3" \
  --data-binary @audio.mp3
```

### Python（非流式）

```python
import os
import requests      # 官方 SDK（deepgram-sdk）各版本写法差异较大，
                     # 这里给等价的裸 HTTP 版本，最稳
r = requests.post(
    'https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language=zh-CN',
    headers={"Authorization": "Token " + os.environ["ASR_API_KEY"],
             "Content-Type": "audio/mp3"},
    data=open("audio.mp3", "rb").read(),   # 原始字节，不是 multipart
    timeout=600)
j = r.json()["results"]["channels"][0]["alternatives"][0]
print(j["transcript"])
for w in j.get("words", []):        # 词级时间轴（秒）
    print(w["start"], w["end"], w["word"])
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

> 鉴权头是 `Authorization: Token <key>`（不是 Bearer）；音频以原始字节放在 body 里。

## ElevenLabs Scribe（协议 `elevenlabs`）
**先设环境变量**：`ASR_API_KEY` → 设置页「ASR 密钥」里填的那个
### curl（非流式）

```bash
curl -X POST "https://api.elevenlabs.io/v1/speech-to-text" \
  -H "xi-api-key: $ASR_API_KEY" \
  -F "model_id=scribe_v1" \
  -F "timestamps_granularity=word" \
  -F "file=@audio.mp3"
```

### Python（非流式）

```python
import os
from elevenlabs.client import ElevenLabs

client = ElevenLabs(api_key=os.environ["ASR_API_KEY"])
with open("audio.mp3", "rb") as f:
    r = client.speech_to_text.convert(        # 非流式
        model_id='scribe_v1', file=f, timestamps_granularity="word")
print(r.text)
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

## Google Gemini（协议 `gemini`）
**先设环境变量**：`ASR_API_KEY` → 设置页「ASR 密钥」里填的那个
### curl（非流式）

```bash
BODY=$(python -c "import base64,json;b=base64.b64encode(open('audio.mp3','rb').read()).decode();print(json.dumps({'contents':[{'parts':[{'inline_data':{'mime_type':'audio/mp3','data':b}},{'text':'请把这段音频逐字转写为文本，只输出转写内容。'}]}]}))")
curl -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent" \
  -H "x-goog-api-key: $ASR_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

### Python（非流式）

```python
import base64, os
from google import genai            # pip install google-genai

client = genai.Client(api_key=os.environ["ASR_API_KEY"])
b64 = base64.b64encode(open("audio.mp3", "rb").read()).decode()
r = client.models.generate_content(        # 非流式
    model='gemini-2.5-flash',
    contents=[{"inline_data": {"mime_type": "audio/mp3", "data": b64}},
              "请把这段音频逐字转写为文本，只输出转写内容。"])
print(r.text)
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

> Gemini 返回纯文本、没有时间轴；本程序按句切分后再按句长占比给出近似时间轴。

## 火山引擎（豆包）录音识别极速版（协议 `volcengine`）
**先设环境变量**：`VOLC_APP_ID` → 控制台的 APP ID；`VOLC_ACCESS_KEY` → 控制台的 Access Token
### curl（非流式）

```bash
BODY=$(python -c "import base64,json,os;b=base64.b64encode(open('audio.mp3','rb').read()).decode();print(json.dumps({'user':{'uid':os.environ['VOLC_APP_ID']},'audio':{'data':b},'request':{'model_name':'bigmodel','enable_punc':True,'show_utterances':True}}))")
curl -X POST "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash" \
  -H "X-Api-App-Key: $VOLC_APP_ID" \
  -H "X-Api-Access-Key: $VOLC_ACCESS_KEY" \
  -H "X-Api-Resource-Id: volc.bigasr.auc_turbo" \
  -H "X-Api-Request-Id: $(uuidgen)" \
  -H "X-Api-Sequence: -1" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

### Python（非流式）

```python
import base64, json, os, uuid
import requests        # 火山没有官方同步 Python SDK，这是等价实现

r = requests.post(
    'https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash',
    headers={"X-Api-App-Key": os.environ["VOLC_APP_ID"],
             "X-Api-Access-Key": os.environ["VOLC_ACCESS_KEY"],
             "X-Api-Resource-Id": "volc.bigasr.auc_turbo",
             "X-Api-Request-Id": str(uuid.uuid4()),
             "X-Api-Sequence": "-1",
             "Content-Type": "application/json"},
    data=json.dumps({"user": {"uid": os.environ["VOLC_APP_ID"]},
                     "audio": {"data": base64.b64encode(
                         open("audio.mp3", "rb").read()).decode()},
                     "request": {"model_name": "bigmodel",
                                 "show_utterances": True}}),
    timeout=600)
print(r.headers.get("X-Api-Status-Code"))     # 20000000 = 成功（在响应头！）
print(r.json()["result"]["text"])
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

> 状态码在**响应头** `X-Api-Status-Code`（`20000000` 为成功）；新版控制台只有一个 API Key 时，把前两个头换成 `X-Api-Key: $ASR_API_KEY`。

## AssemblyAI（协议 `assemblyai`）
**先设环境变量**：`ASR_API_KEY` → 设置页「ASR 密钥」里填的那个
### curl（非流式）

```bash
# 1) 上传本地文件（raw bytes，不是 multipart）
UP=$(curl -s -X POST "https://api.assemblyai.com/v2/upload" \
  -H "authorization: $ASR_API_KEY" --data-binary @audio.mp3 | jq -r .upload_url)
# 2) 提交转写任务
ID=$(curl -s -X POST "https://api.assemblyai.com/v2/transcript" \
  -H "authorization: $ASR_API_KEY" -H "content-type: application/json" \
  -d '{"audio_url": "'$UP'", "speech_models": ["universal-3-pro", "universal-2"]}' | jq -r .id)
# 3) 轮询到完成（非流式：结果一次性取回）
while :; do
  S=$(curl -s "https://api.assemblyai.com/v2/transcript/$ID" -H "authorization: $ASR_API_KEY"
        | jq -r .status)
  [ "$S" = "completed" ] && break; [ "$S" = "error" ] && break; sleep 3
done
curl -s "https://api.assemblyai.com/v2/transcript/$ID" -H "authorization: $ASR_API_KEY" | jq -r .text
```

### Python（非流式）

```python
import os
import assemblyai as aai           # pip install assemblyai

aai.settings.api_key = os.environ["ASR_API_KEY"]
cfg = aai.TranscriptionConfig(speech_models=['universal-3-pro', 'universal-2'], language_detection=True)
t = aai.Transcriber().transcribe("audio.mp3", config=cfg)   # 阻塞到完成
print(t.text)
for w in (t.words or []):          # 词级时间轴（毫秒）
    print(w.start, w.end, w.text)
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

> 鉴权头是 `authorization: <key>`（**不带 Bearer**）；`speech_models` 必填（官方无默认值）；词级时间轴单位是**毫秒**。curl 示例用到 jq（Windows 上直接看 Python 版即可）。

## 本地 faster-whisper（不联网）（协议 `local`）

### Python（非流式）

```python
from faster_whisper import WhisperModel

model = WhisperModel('large-v3', device="auto")   # 或模型目录
segments, info = model.transcribe("audio.mp3", language="zh")
print("".join(s.text for s in segments))
```

> 非流式：一次请求（或上传→提交→轮询）返回完整结果，不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。

> 示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。

> 本地模型在本程序的「设置 → ASR 语音识别 → 本地独立模型」里配。
