# @version 2.1.0
"""本地 ASR（自研，替代 videocaptioner.core.asr.faster_whisper）。

P2 接缝配套模块：``faster-whisper``（MIT 组件）保留，但**执行链**改由本
模块负责——它把音频交给随包的独立可执行程序，转成 SRT 后解析成字幕段。

编写依据
--------
* 接口契约：构造参数（模型名/目录/语言/设备/VAD/文本处理参数）、覆写点
  ``_run`` / ``_make_segments`` / ``_get_key``、异常类型（``EnvironmentError``
  表示程序缺失、``ValueError`` 表示无音频数据）；
* 可观察行为：命令行参数构造、幻觉文本过滤、缓存键形式。

**缓存键是持久化契约**：引擎用 ``f"{crc32_hex}-{md5(cmd)}"``——把完整命令
md5 进去是为了「换一个参数就算另一份结果」。本模块沿用同一形式，否则同一
音频换模型后���会命中上一模型的缓存（字幕内容完全错位）。

**幻觉文本过滤是行为契约**：语音模型在长静音/纯音乐段会吐出固定套话
（「请不吝点赞 订阅 转发」这类），不滤掉就会出现在成片字幕里。这不是
洁癖——是明确的产品要求。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile

from engine_asr import BaseASR, ASRStatus
from engine_asr_data import ASRData, ASRDataSeg

__all__ = ["FasterWhisperASR", "HALLUCINATION_KEYWORDS", "is_rtx_50_series"]

#: 幻觉文本关键词——语音模型在静音/音乐段常吐的固定套话。
#: 命中即整条丢弃（不是替换、不是降权：这些句子压根不是说话内容）。
HALLUCINATION_KEYWORDS = (
    "请不吝点赞 订阅 转发",
    "打赏支持明镜",
)

#: 音乐标记前缀（以这些符号开头的条目是音效标注，不是台词）
_MUSIC_PREFIXES = ("【", "[", "(", "（")


def is_rtx_50_series() -> bool:
    """是否 RTX 50 系显卡（需 float16 计算类型）。

    50 系（Blackwell）在默认 int8/float32 下会报错或精度异常，必须显式
    指定 ``--compute_type float16``。GPUtil 不可用时返回 False——
    此时走默认计算类型，行为退化但不崩。
    """
    try:
        import GPUtil
    except ImportError:
        return False
    try:
        for g in GPUtil.get_gpus():
            name = (g.name or "").upper()
            if "50" in name and ("RTX" in name or "GEFORCE" in name):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


class FasterWhisperASR(BaseASR):
    """本地 faster-whisper 转写。

    程序选择：``cpu`` 设备优先用 ``faster-whisper-xxl``（含人声分离等增强），
    没有则退回 ``faster-whisper``；``cuda`` 设备必须有 xxl。
    程序找不到时抛 ``EnvironmentError``——这是「需要用户去下载依赖」的场景，
    必须明确报错而不是静默切远端。
    """

    def __init__(self, audio_input=None, faster_whisper_program: str = "",
                 whisper_model: str = "base", model_dir: str = "",
                 language: str = "zh", device: str = "cpu",
                 output_dir=None, output_format: str = "srt",
                 use_cache: bool = False, need_word_time_stamp: bool = False,
                 vad_filter: bool = True, vad_threshold: float = 0.4,
                 vad_method: str = "", ff_mdx_kim2: bool = False,
                 one_word: int = 0, prompt=None, **_ignored):
        super().__init__(audio_input, use_cache, need_word_time_stamp)

        self.model_path = whisper_model
        self.model_dir = model_dir
        self.faster_whisper_program = faster_whisper_program
        self.language = language
        self.device = device
        self.output_dir = output_dir
        self.output_format = output_format
        self.vad_filter = vad_filter
        self.vad_threshold = vad_threshold
        self.vad_method = vad_method
        self.ff_mdx_kim2 = ff_mdx_kim2
        self.prompt = prompt or ""
        # 文本重排参数（one_word 与 sentence 互斥：引擎同款，sentence 优先）
        self.one_word = 1 if one_word else 0
        self.sentence = False
        self.max_line_width = 100
        self.max_line_count = 1
        self.max_comma = 20
        self.max_comma_cent = 50

        self.process = None
        self._resolve_program()

    # ---------- 程序定位 ----------
    def _resolve_program(self):
        if self.device == "cpu":
            if shutil.which("faster-whisper-xxl"):
                self.faster_whisper_program = "faster-whisper-xxl"
            elif not shutil.which("faster-whisper"):
                raise EnvironmentError(
                    "faster-whisper program not found，请确保已经下载。")
            else:
                self.faster_whisper_program = "faster-whisper"
                self.vad_method = ""      # 精简版不支持 vad_method
        elif self.device == "cuda":
            if not shutil.which("faster-whisper-xxl"):
                raise EnvironmentError(
                    "faster-whisper-xxl 程序未找到，请确保已经下载。")
            self.faster_whisper_program = "faster-whisper-xxl"

    # ---------- 命令行 ----------
    def _build_command(self, audio_input: str):
        """构造命令行。参数集合与顺序即缓存键的一部分，勿随意调整。"""
        cmd = [str(self.faster_whisper_program),
               "-m", str(self.model_path),
               "--print_progress"]
        if self.model_dir:
            cmd.extend(["--model_dir", str(self.model_dir)])
        cmd.extend([str(audio_input), "-d", self.device,
                    "--output_format", self.output_format])
        # 语言为空 ⇒ 不传 -l，让程序自动检测
        if self.language:
            cmd.extend(["-l", self.language])
        cmd.extend(["-o", str(self.output_dir) if self.output_dir else "source"])

        if self.vad_filter:
            cmd.extend(["--vad_filter", "true",
                        "--vad_threshold", "%.2f" % self.vad_threshold])
            if self.vad_method:
                cmd.extend(["--vad_method", self.vad_method])
        else:
            cmd.extend(["--vad_filter", "false"])

        if self.ff_mdx_kim2 and self.faster_whisper_program.startswith(
                "faster-whisper-xxl"):
            cmd.append("--ff_mdx_kim2")

        cmd.extend(["--one_word", str(self.one_word)])

        if self.prompt:
            cmd.extend(["--initial_prompt", self.prompt])
        cmd.extend(["--beep_off"])

        if is_rtx_50_series():
            cmd.extend(["--compute_type", "float16"])
        return cmd

    # ---------- 缓存键 ----------
    def _get_key(self):
        """``crc32-hex + md5(完整命令)``——换任何参数都算另一份结果。"""
        cmd_hash = hashlib.md5(str(self._build_command("")).encode()).hexdigest()
        return "%s-%s" % (self.crc32_hex, cmd_hash)

    # ---------- 执行 ----------
    def _run(self, callback=None, **_kwargs) -> str:
        if callback is None:
            def callback(_x, _y):
                return None

        with tempfile.TemporaryDirectory() as temp_path:
            wav_path = os.path.join(temp_path, "audio.wav")
            if isinstance(self.audio_input, str):
                shutil.copy2(self.audio_input, wav_path)
            elif self.file_binary:
                with open(wav_path, "wb") as f:
                    f.write(self.file_binary)
            else:
                raise ValueError("No audio data available")

            cmd = self._build_command(wav_path)
            callback(*ASRStatus.TRANSCRIBING.with_progress(5))

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, cwd=temp_path)
            self.process = proc
            lines = []
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                lines.append(line)
                pct = _parse_progress(line)
                if pct is not None:
                    callback(*ASRStatus.TRANSCRIBING.with_progress(pct))
            rc = proc.wait()
            if rc != 0:
                tail = "\n".join(lines[-8:])
                raise RuntimeError("faster-whisper 退出码 %d：\n%s" % (rc, tail))

            srt = _find_output_srt(temp_path)
            if not srt:
                raise RuntimeError("faster-whisper 未产出字幕文件：\n%s"
                                   % "\n".join(lines[-8:]))
            with open(srt, encoding="utf-8-sig", errors="replace") as f:
                return f.read()

    def _make_segments(self, resp_data: str):
        """解析 SRT 并过滤音乐标记与幻觉文本。"""
        data = ASRData.from_srt(resp_data)
        out = []
        for seg in data.segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            if text.startswith(_MUSIC_PREFIXES):
                continue
            if any(k in text for k in HALLUCINATION_KEYWORDS):
                continue
            out.append(seg)
        return out


_PROGRESS_RE = re.compile(r"(\d{1,3})\s*%")


def _parse_progress(line: str):
    """从程序输出里取百分比（取不到返回 None）。"""
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    try:
        return max(0, min(100, int(m.group(1))))
    except ValueError:
        return None


def _find_output_srt(temp_path: str):
    """在临时目录里找程序产出的 SRT（可能改名、可能落在 source 子目录）。"""
    for root, _dirs, files in os.walk(temp_path):
        for name in files:
            if name.lower().endswith(".srt"):
                return os.path.join(root, name)
    return None