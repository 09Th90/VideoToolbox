# -*- coding: utf-8 -*-
# @version 2.6.0
"""自研 UI 契约静态校验（P3）。

在**无法实例化 Qt**（本机 QApplication 挂起）的前提下，用 AST 静态校验：
``vt_engine_ui`` 各页是否暴露了宿主 ``video_toolbox_qt.py`` / 引擎内部所依赖的
全部成员（方法、信号、实例属性）。成员缺失会导致运行期 AttributeError 或
「功能悄悄没了」，这里在提交前就拦下。

契约来源：对宿主与引擎调用点的穷尽梳理（见规格 P3）。

用法： python scripts/dev/vt_ui_contract.py
"""
import ast
import os
import sys

SRC = os.path.join(os.getcwd(), "src", "vt_engine_ui")

# 每个源文件 -> {类名: set(需要的成员名)}
# 成员可以是：方法/信号（类体定义）或实例属性（方法体内 self.X= 赋值）
CONTRACT = {
    "home_interface.py": {
        "HomeInterface": {
            "pivot", "stackedWidget", "vBoxLayout", "_current_task_id",
            "task_creation_interface", "transcription_interface",
            "subtitle_optimization_interface", "video_synthesis_interface",
            "switch_to_transcription", "switch_to_subtitle_optimization",
            "switch_to_video_synthesis", "addSubInterface",
            "onCurrentIndexChanged", "closeEvent",
        },
    },
    "task_creation_interface.py": {
        "TaskCreationInterface": {
            "finished", "setup_ui", "setup_values", "setup_signals",
            "main_layout", "logo_label", "search_input", "start_button",
            "status_label", "progress_bar", "info_label", "donate_button",
            "log_button", "dropEvent", "dragEnterEvent", "process",
            "set_task", "update_info", "show_log_window",
            # v2.1.0：识别到网页链接 → 由宿主接走跳「视频下载」；
            # 另有 _is_valid_url / _process_url / on_video_download_finished
            # 保留（引擎回退路径与兼容钩子仍会碰到）。
            "url_detected", "_is_valid_url", "_process_url",
            "on_video_download_finished", "create_task",
        },
        "LogWindow": {"update_log", "open_log_folder", "load_last_lines"},
    },
    "transcription_interface.py": {
        "TranscriptionInterface": {
            "finished", "main_layout", "command_bar", "open_file_action",
            "model_button", "model_menu", "video_info_card",
            "transcription_setting_card", "is_processing", "task",
            "_setup_command_bar", "_setup_signals", "_set_value",
            "on_transcription_model_changed", "_on_transcript_finished",
            "_on_file_select", "update_info", "set_task", "process",
            "dropEvent", "dragEnterEvent", "closeEvent", "_vt_heal_stale",
        },
        "VideoInfoCard": {
            "finished", "start_button", "open_folder_button", "progress_ring",
            "video_thumbnail", "video_title", "transcript_thread",
            "reset_ui", "set_task", "update_info", "start_transcription",
            "stop", "on_transcript_finished",
        },
    },
    "subtitle_interface.py": {
        "SubtitleInterface": {
            "finished", "main_layout", "command_bar", "subtitle_table", "model",
            "optimize_button", "translate_button", "layout_button",
            "target_language_button", "start_button", "cancel_button",
            "progress_bar", "status_label", "subtitle_path", "task",
            "bottom_layout", "prompt_button",
            "set_task", "process", "load_subtitle_file", "update_info",
            "start_subtitle_optimization", "dropEvent", "dragEnterEvent",
            "closeEvent", "keyPressEvent",
        },
        "SubtitleTableModel": {
            "_data", "load_data", "data", "setData", "headerData",
            "rowCount", "columnCount", "flags", "update_data", "update_all",
        },
        "PromptDialog": {"text_edit", "save_prompt", "get_prompt"},
    },
    "setting_interface.py": {
        "SettingInterface": {
            "scrollWidget", "expandLayout", "settingLabel",
            "transcribeGroup", "llmGroup", "translate_serviceGroup",
            "translateGroup", "subtitleGroup", "saveGroup", "personalGroup",
            "aboutGroup", "openaiOfficialApiCard", "translatorServiceCard",
            "subtitleCorrectCard", "subtitleTranslateCard", "targetLanguageCard",
            "needReflectTranslateCard", "threadNumCard", "deeplxEndpointCard",
            "batchSizeCard", "transcribeModelCard", "savePathCard",
            "cacheEnabledCard", "llmServiceCard", "checkLLMConnectionCard",
            "checkWhisperConnectionCard", "llm_service_configs",
        },
    },
    "components.py": {
        "TranscriptionSettingCard": {"empty_widget", "stacked_widget",
                                     "main_layout", "on_model_changed"},
        "TranscriptionSettingDialog": {"viewLayout", "output_format_card",
                                       "titleLabel"},
        "LineEditSettingCard": {"lineEdit", "setValue"},
        "EditComboBoxSettingCard": {"comboBox", "setValue", "setItems", "addItems"},
    },
    "subtitle_setting_dialog.py": {
        "SubtitleSettingDialog": {"viewLayout", "split_card",
                                  "word_count_cjk_card", "word_count_english_card"},
        "SpinBoxSettingCard": {"spinBox", "setValue"},
    },
    "video_synthesis_interface.py": {
        "VideoSynthesisInterface": {"finished", "set_task", "process", "task"},
    },
}


def _class_members(cls: ast.ClassDef):
    """收集类可见成员：类体方法/属性 + 所有方法体内 self.X 赋值。"""
    names = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    # 扫描方法体内所有 self.X 引用（写入或读取）——读取覆盖「继承自基类」的属性
    # （如 MessageBoxBase.viewLayout / ScrollArea.widget），它们不在本类赋值但存在。
    for sub in ast.walk(cls):
        if (isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name) and sub.value.id == "self"):
            names.add(sub.attr)
    return names


def main():
    total_missing = 0
    for fname, classes in CONTRACT.items():
        path = os.path.join(SRC, fname)
        if not os.path.isfile(path):
            print(f"[MISS FILE] {fname}")
            total_missing += 1
            continue
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), fname)
        defined = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        for cname, required in classes.items():
            cls = defined.get(cname)
            if cls is None:
                print(f"[MISS CLASS] {fname}::{cname}")
                total_missing += 1
                continue
            have = _class_members(cls)
            missing = sorted(required - have)
            if missing:
                print(f"[MISS MEMBER] {fname}::{cname} -> {missing}")
                total_missing += len(missing)
            else:
                print(f"[OK] {fname}::{cname} ({len(required)} members)")
    print("=" * 50)
    print("CONTRACT RESULT:", "PASS" if total_missing == 0 else f"FAIL ({total_missing} missing)")
    return 0 if total_missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
