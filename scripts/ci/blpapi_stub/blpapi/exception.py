"""blpapi.exception CI stub — 仅提供异常类型占位, 无真实 Bloomberg 逻辑.

真实 blpapi 的 `InvalidStateException` 在会话未启动/已终止时由 `nextEvent`
抛出；backend 代码据此判定会话终止并重建。CI 里只需该类型可被 import 与
`except` 捕获。
"""


class BlpapiException(Exception):
    pass


class InvalidStateException(BlpapiException):
    pass
