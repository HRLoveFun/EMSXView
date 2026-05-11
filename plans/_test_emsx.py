"""Quick EMSX service availability test — no external dependencies."""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("emsx_test")

try:
    import blpapi
except ImportError:
    logger.error("blpapi not installed")
    sys.exit(1)

# Connect
session_opts = blpapi.SessionOptions()
session_opts.setServerHost("127.0.0.1")
session_opts.setServerPort(8194)
session = blpapi.Session(session_opts)
logger.info("Starting session...")
if not session.start():
    logger.error("Session start failed")
    sys.exit(1)
logger.info("Session started")

# Open EMSX history service
SERVICE = os.getenv("EMSX_HISTORY_SERVICE", "//blp/emsx.history")
logger.info("Opening service %s ...", SERVICE)
if not session.openService(SERVICE):
    logger.error("Failed to open service %s", SERVICE)
    session.stop()
    sys.exit(1)
logger.info("Service %s opened OK", SERVICE)

# Send a minimal GetFills request
service = session.getService(SERVICE)
request = service.createRequest("GetFills")
request.set("FromDateTime", "2026-05-08T00:00:00.000+00:00")
request.set("ToDateTime", "2026-05-08T23:59:59.000+00:00")
scope = request.getElement("Scope")
scope.setChoice("TradingSystem")
scope.setElement("TradingSystem", True)

logger.info("Sending GetFills request...")
session.sendRequest(request)

# Wait for response with 30s timeout
fills = []
consecutive_timeouts = 0
done = False
while not done:
    logger.info("Waiting for nextEvent(timeout=30000)...")
    try:
        event = session.nextEvent(30000)
    except Exception as e:
        logger.error("nextEvent exception: %s", e)
        break

    if event.eventType == blpapi.Event.PARTIAL_RESPONSE:
        consecutive_timeouts = 0
        count = sum(1 for _ in event)
        logger.info("PARTIAL_RESPONSE: %d messages", count)
        for msg in event:
            if msg.messageType == "GetFillsResponse":
                fills.append("<fill>")
    elif event.eventType == blpapi.Event.RESPONSE:
        consecutive_timeouts = 0
        count = sum(1 for _ in event)
        logger.info("RESPONSE: %d messages, total=%d fills", count, len(fills))
        done = True
    elif event.eventType == blpapi.Event.REQUEST_STATUS:
        for msg in event:
            if msg.hasElement("ErrorInfo"):
                err = msg.getElement("ErrorInfo")
                logger.error("REQUEST_STATUS error: %s", err)
        done = True
    elif event.eventType == blpapi.Event.TIMEOUT:
        consecutive_timeouts += 1
        logger.warning("TIMEOUT #%d", consecutive_timeouts)
        if consecutive_timeouts >= 2:
            logger.error("2 consecutive timeouts — service not responding")
            done = True
    elif event.eventType == blpapi.Event.SESSION_STATUS:
        logger.info("SESSION_STATUS event")
    else:
        logger.info("Other event type: %s", event.eventType)

session.stop()
logger.info("Test complete. Total fills: %d", len(fills))
