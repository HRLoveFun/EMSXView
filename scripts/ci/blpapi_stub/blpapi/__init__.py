"""blpapi CI stub — 仅满足 import 期占位, 无真实 Bloomberg 逻辑.

GitHub Actions 公共 runner 无法安装 blpapi（Bloomberg 官方仅通过私有源分发）。
本 stub 供 CI 边界/回归测试使用：backend 测试全部用 MagicMock 模拟真实服务，
blpapi 仅需在 import 期提供占位符号即可。禁止在生产环境使用。
"""


class Event:
    RESPONSE = "RESPONSE"
    PARTIAL_RESPONSE = "PARTIAL_RESPONSE"
    SUBSCRIPTION_DATA = "SUBSCRIPTION_DATA"
    SESSION_STATUS = "SESSION_STATUS"
    ADMIN = "ADMIN"
    SUBSCRIPTION_STATUS = "SUBSCRIPTION_STATUS"
    TIMEOUT = "TIMEOUT"

    def eventType(self) -> str:
        return self.RESPONSE

    def __iter__(self):
        return iter(())


class Request:
    def __init__(self, *args, **kwargs) -> None:
        pass


class SubscriptionList:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def add(self, *args, **kwargs) -> None:
        pass


class SessionOptions:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def setServerHost(self, *args, **kwargs) -> None:
        pass

    def setServerPort(self, *args, **kwargs) -> None:
        pass

    def setAuthenticationOptions(self, *args, **kwargs) -> None:
        pass


class Session:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self, *args, **kwargs) -> bool:
        return False

    def nextEvent(self, *args, **kwargs) -> Event:
        return Event()

    def openService(self, *args, **kwargs) -> bool:
        return True

    def getService(self, *args, **kwargs) -> "Service":
        raise RuntimeError("stub: 不应在 CI 中调用真实 Bloomberg 服务")

    def sendRequest(self, *args, **kwargs) -> None:
        raise RuntimeError("stub: 不应在 CI 中调用真实 Bloomberg 服务")


class Service:
    def __init__(self, *args, **kwargs) -> None:
        pass


class Element:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def getElementAsFloat(self, *args, **kwargs) -> float:
        return 0.0


class Message:
    def __init__(self, *args, **kwargs) -> None:
        pass


class Subscription:
    def __init__(self, *args, **kwargs) -> None:
        pass


class CorrelationId:
    def __init__(self, *args, **kwargs) -> None:
        pass
