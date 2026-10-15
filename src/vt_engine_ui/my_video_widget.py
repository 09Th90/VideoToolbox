# -*- coding: utf-8 -*-
# @version 2.3.0
"""视频预览弹窗（可选能力，惰性代理到引擎实现）。

本 UI 层不重写视频预览控件：它依赖 ``vlc`` + qfluentwidgets 多媒体播放条（均为
保留组件），且在视频工具箱的可达界面中并不出现（字幕页的视频播放入口默认注释
关闭）。此处提供一个惰性代理：仅当确有代码请求时，才回退到引擎实现，并施加与
原品牌补丁一致的中性化（窗口标题「视频预览」+ 跟随宿主图标）。

缺 ``vlc`` 时导入失败——调用方本就按 best-effort 处理（try/except 降级为 None）。
"""
from __future__ import annotations


def MyVideoWidget(parent=None):
    """构造视频预览弹窗；缺可选依赖 vlc 时抛出，由调用方兜底。"""
    from videocaptioner.ui.components.MyVideoWidget import MyVideoWidget as _Base

    class _VtVideoWidget(_Base):
        _vt_patched = True

        def __init__(self, p=None):
            super().__init__(p)
            self.setWindowTitle("视频预览")
            try:
                from PySide6.QtWidgets import QApplication
                icon = QApplication.windowIcon()
                if not icon.isNull():
                    self.setWindowIcon(icon)
            except Exception:  # noqa: BLE001
                pass

    return _VtVideoWidget(parent)
