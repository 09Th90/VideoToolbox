# @version 2.5.1
"""Wiki 补全：四个游戏 wiki 的角色名单 -> 对象库作品归属。

并行开发期约束：只读对象库、只写补丁 JSON，不改源文件。
"""
__all__ = ["client", "sources", "fetch"]
