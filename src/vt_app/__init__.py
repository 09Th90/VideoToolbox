# -*- coding: utf-8 -*-
# @version 3.1.0
"""vt_app —— GUI 壳基础设施（2026-11-15 功能解耦阶段②，从 video_toolbox_qt.py 下沉）。

本包只放**与具体业务页面无关**的壳层设施：启动诊断 / 崩溃守卫 / 控件基建 /
启动调度器 / 惰性页外壳 / 消息总线 / 引擎 UI 预热 / 边框热区。

依赖红线：
* vt_app **不 import 具体功能**（features.*）——注册表由入口注入；
* 页面（features/<id>/page.py）只经本包基建 + 注册表服务取能力，
  禁止反向 import GUI 入口 video_toolbox_qt；
* 本包代码与原单体逐字同源（行为零变化），调用方经入口再导出名访问。
"""