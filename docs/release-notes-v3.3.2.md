<!-- @version 3.3.2 -->
# 视频工具箱 v3.3.2 发布说明

- 发布日期：2026-11-27
- 基线版本：v3.3.1（2026-11-26）
- 说明：本版为 **UI 去分层 + 打包修复** 维护版，不改变业务命令与配置 schema。

## 一、界面：去分层结构

- `vt_app/widgets.card()` 从 `UICard` 卡片工厂改为**扁平分区**：分组标题、说明、内容、标题下 1px 分区线；不再绘制外层卡片底板、圆角、描边和 hover。
- 新增 `surface_card()`，只用于首页入口、视频库缩略图等真正需要单层卡片的场景。
- 新增 `FlatBody` 单层内容面（无圆角、无边框、无阴影），继续复用 `section_dim_card_fill()`，外观页“卡片不透明度”滑杆仍然生效。
- 设置页 10 个二级页 builder、视频下载/合并/切片、实时字幕、流水线、字幕处理宿主、AI 托管、自动化等页面同步扁平化；输入框、表格、日志只保留各自一层边界。
- 第三方字幕引擎、qfluentwidgets 原生设置卡、视频库缩略图等**单层卡片保留**；第三方引擎内部布局不重写。
- 修复发布素材页 `card(self)` 的旧调用，避免该页实例化时报错。
- 正式截图 18 张已按去分层版本重截（1440×900，浅色 50%/50%）。

## 二、打包：PyAV FFmpeg 运行库保护

- 修正 PyInstaller 瘦身名单：FFmpeg 五前缀从 `_DROP_BINARIES` 移出，改由 `_QT_FFMPEG_PREFIXES` 单独过滤，并跳过 `av.libs`。
- 构建期新增硬校验：`av.libs` 缺 `avcodec / avformat / avutil / swscale / swresample` 时直接中止，避免打包成功但本地 ASR 在 `import av` 时报 `_core` DLL 加载失败。

## 三、校准知识同步

- 同步战双、鸣潮、明日方舟、终末地的最新术语与漏译体检规则；单文件校准脚本由 `src/calib_core` 重新生成，学习库由后台同步通道维护。

## 四、验证

- `scripts/dev/_selftest_gui.py`：全部通过。
- `_selftest_vt_fluent_qss.py`：PASS 54。
- `_selftest_vt_fluent_widgets.py`：PASS 224。
- 本次仅做源码推送，安装包需另行构建后再更新 README 下载入口。
