"""Check if msg.messageType is a property or method."""
import blpapi

s = blpapi.Session(blpapi.SessionOptions())
s.start()
s.openService("//blp/emsx.history")
svc = s.getService("//blp/emsx.history")
req = svc.createRequest("GetFills")
req.set("FromDateTime", "2026-05-08T00:00:00.000+00:00")
req.set("ToDateTime", "2026-05-08T23:59:59.000+00:00")
scope = req.getElement("Scope")
scope.setChoice("TradingSystem")
scope.setElement("TradingSystem", True)
s.sendRequest(req)
ev = s.nextEvent(3000)
for msg in ev:
    mt = msg.messageType
    print(f"messageType value: {mt}")
    print(f"type: {type(mt).__name__}")
    print(f"callable: {callable(mt)}")
    if callable(mt):
        val = mt()
        print(f"  calling messageType() gives: {val}")
        print(f"  == blpapi.Name('GetFillsResponse'): {val == blpapi.Name('GetFillsResponse')}")
    else:
        print(f"  == blpapi.Name('GetFillsResponse'): {mt == blpapi.Name('GetFillsResponse')}")
    break
s.stop()
