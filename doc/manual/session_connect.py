# session_connect.py
# Bloomberg EMSX API - Session Connection Examples
# Source: EMSX-API-Complete-Guide.md - "Creating a session" section
# Quick Reference: Section 1.1 Quick Start

import blpapi
import sys


# =============================================================================
# Synchronous Session Connection
# =============================================================================
def connect_sync():
    """Connect to Bloomberg EMSX API synchronously."""
    sessionOptions = blpapi.SessionOptions()
    sessionOptions.setServerHost("localhost")
    sessionOptions.setServerPort(8194)

    session = blpapi.Session(sessionOptions)

    if not session.start():
        print("Failed to start session.")
        return None

    # Open EMSX service
    # Production: "//blp/emapisvc"
    # UAT/Beta:   "//blp/emapisvc_beta"
    if not session.openService("//blp/emapisvc_beta"):
        print("Failed to open service.")
        session.stop()
        return None

    print("Session started and service opened (sync).")
    return session


# =============================================================================
# Asynchronous Session Connection
# =============================================================================
SESSION_STARTED         = blpapi.Name("SessionStarted")
SESSION_STARTUP_FAILURE = blpapi.Name("SessionStartupFailure")
SERVICE_OPENED          = blpapi.Name("ServiceOpened")
SERVICE_OPEN_FAILURE    = blpapi.Name("ServiceOpenFailure")

d_service = "//blp/emapisvc_beta"
d_host = "localhost"
d_port = 8194
bEnd = False


class SessionEventHandler():

    def processEvent(self, event, session):
        try:
            if event.eventType() == blpapi.Event.SESSION_STATUS:
                self.processSessionStatusEvent(event, session)

            elif event.eventType() == blpapi.Event.SERVICE_STATUS:
                self.processServiceStatusEvent(event, session)

            else:
                self.processMiscEvents(event)

        except:
            print("Exception:  %s" % sys.exc_info()[0])

        return False

    def processSessionStatusEvent(self, event, session):
        print("Processing SESSION_STATUS event")
        for msg in event:
            if msg.messageType() == SESSION_STARTED:
                print("Session started...")
                session.openServiceAsync(d_service)
            elif msg.messageType() == SESSION_STARTUP_FAILURE:
                print("Error: Session startup failed", file=sys.stderr)
            else:
                print(msg)

    def processServiceStatusEvent(self, event, session):
        print("Processing SERVICE_STATUS event")
        for msg in event:
            if msg.messageType() == SERVICE_OPENED:
                print("Service opened...")
                global bEnd
                bEnd = True
            elif msg.messageType() == SERVICE_OPEN_FAILURE:
                print("Error: Service failed to open", file=sys.stderr)

    def processMiscEvents(self, event):
        print("Processing " + event.eventType() + " event")
        for msg in event:
            print("MESSAGE: %s" % (msg.tostring()))


def connect_async():
    """Connect to Bloomberg EMSX API asynchronously."""
    sessionOptions = blpapi.SessionOptions()
    sessionOptions.setServerHost(d_host)
    sessionOptions.setServerPort(d_port)

    print("Connecting to %s:%d" % (d_host, d_port))

    eventHandler = SessionEventHandler()
    session = blpapi.Session(sessionOptions, eventHandler.processEvent)

    if not session.startAsync():
        print("Failed to start session.")
        return

    global bEnd
    while bEnd == False:
        pass

    print("Async session connected and service opened.")
    session.stop()


if __name__ == "__main__":
    print("Bloomberg - EMSX API Example - Session Connection")
    print("=" * 50)

    # Uncomment one of the following:

    # Option 1: Synchronous
    # session = connect_sync()
    # if session:
    #     session.stop()

    # Option 2: Asynchronous
    try:
        connect_async()
    except KeyboardInterrupt:
        print("Ctrl+C pressed. Stopping...")
