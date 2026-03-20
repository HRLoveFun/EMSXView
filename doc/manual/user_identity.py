# user_identity.py
# Bloomberg EMSX API - User Identity Management (Trading API Server)
# Source: EMSX-API-Complete-Guide.md - "User Identity Management" section
# Quick Reference: Section 6 Trading API Server
#
# This example demonstrates creating and using user identities for
# server-side EMSX API applications (Trading API Server).
# On desktop, the logged-in terminal user's identity is implicit.
# On server, identities must be explicitly created via //blp/apiauth.
#
# Flow:
#   1. Start session and open both apiauth and emapisvc services
#   2. Create an authorization request with emrsId and ipAddress
#   3. Create an empty Identity object via session.createIdentity()
#   4. Send authorization request and wait for AuthorizationSuccess
#   5. Use the populated Identity in all sendRequest/subscribe calls

import blpapi
import sys

AUTHORIZATION_SUCCESS = blpapi.Name("AuthorizationSuccess")
AUTHORIZATION_FAILURE = blpapi.Name("AuthorizationFailure")

SESSION_STARTED = blpapi.Name("SessionStarted")
SESSION_TERMINATED = blpapi.Name("SessionTerminated")
SESSION_STARTUP_FAILURE = blpapi.Name("SessionStartupFailure")
SESSION_CONNECTION_UP = blpapi.Name("SessionConnectionUp")
SESSION_CONNECTION_DOWN = blpapi.Name("SessionConnectionDown")

SERVICE_OPENED = blpapi.Name("ServiceOpened")
SERVICE_OPEN_FAILURE = blpapi.Name("ServiceOpenFailure")

d_auth = "//blp/apiauth"
d_emsx = "//blp/emapisvc_beta"
d_host = "localhost"
d_port = 8194

# User credentials for authorization
d_user = "myEMRSID"          # EMRS ID of the target user
d_ip = "10.20.30.40"         # IP address of the server

bEnd = False


class SessionEventHandler(object):

    def __init__(self):
        self.identity = None
        self.requestID = None

    def processEvent(self, event, session):
        try:
            if event.eventType() == blpapi.Event.SESSION_STATUS:
                self.processSessionStatusEvent(event, session)
            elif event.eventType() == blpapi.Event.SERVICE_STATUS:
                self.processServiceStatusEvent(event, session)
            elif event.eventType() == blpapi.Event.RESPONSE:
                self.processResponseEvent(event, session)
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
                # First open the authentication service
                session.openServiceAsync(d_auth)
            elif msg.messageType() == SESSION_STARTUP_FAILURE:
                print("Error: Session startup failed", file=sys.stderr)
                global bEnd
                bEnd = True
            elif msg.messageType() == SESSION_TERMINATED:
                print("Session terminated")
                bEnd = True
            elif msg.messageType() == SESSION_CONNECTION_UP:
                print("Session connection is up")
            elif msg.messageType() == SESSION_CONNECTION_DOWN:
                print("Session connection is down")

    def processServiceStatusEvent(self, event, session):
        print("Processing SERVICE_STATUS event")
        for msg in event:
            if msg.messageType() == SERVICE_OPENED:
                serviceName = msg.asElement().getElementAsString("serviceName")
                print("Service opened: %s" % serviceName)

                if serviceName == d_auth:
                    # Auth service is open, send authorization request
                    self.sendAuthRequest(session)
                elif serviceName == d_emsx:
                    # EMSX service is open, now we can make requests
                    print("EMSX service ready - can now send requests with identity")
                    self.sendDataRequest(session)

            elif msg.messageType() == SERVICE_OPEN_FAILURE:
                print("Error: Service failed to open", file=sys.stderr)

    def sendAuthRequest(self, session):
        """Create and send an authorization request for a user identity."""
        authService = session.getService(d_auth)
        authReq = authService.createAuthorizationRequest()
        authReq.set("emrsId", d_user)
        authReq.set("ipAddress", d_ip)
        self.identity = session.createIdentity()

        print("Sending authorization request: %s" % (authReq))

        self.requestID = session.sendAuthorizationRequest(authReq, self.identity)

        print("Authorization request sent.")

    def processResponseEvent(self, event, session):
        print("Processing RESPONSE event")
        for msg in event:
            print("MESSAGE: %s" % msg)

            if msg.messageType() == AUTHORIZATION_SUCCESS:
                print("Authorization successful....")
                print("SeatType: %s" % (self.identity.getSeatType()))
                # Identity is now populated - open the EMSX service
                session.openServiceAsync(d_emsx)

            elif msg.messageType() == AUTHORIZATION_FAILURE:
                print("Authorization failed....")
                # Insert code here to automatically retry authorization
                global bEnd
                bEnd = True

            elif msg.hasElement("EMSX_SEQUENCE"):
                # This is a response to an EMSX request
                emsx_sequence = msg.getElementAsInteger("EMSX_SEQUENCE")
                emsx_message = msg.getElementAsString("MESSAGE")
                print("EMSX_SEQUENCE: %d" % emsx_sequence)
                print("MESSAGE: %s" % emsx_message)
                bEnd = True

    def sendDataRequest(self, session):
        """Example: Send a CreateOrder request using the authenticated identity.

        Key difference from Desktop API:
          Desktop (DAPI):  session.sendRequest(request, requestID)
          Server:          session.sendRequest(request, self.identity, requestID)
        """
        service = session.getService(d_emsx)
        request = service.createRequest("CreateOrder")

        request.set("EMSX_TICKER", "IBM US Equity")
        request.set("EMSX_AMOUNT", 1000)
        request.set("EMSX_ORDER_TYPE", "MKT")
        request.set("EMSX_TIF", "DAY")
        request.set("EMSX_HAND_INSTRUCTION", "ANY")
        request.set("EMSX_SIDE", "BUY")

        print("Sending CreateOrder request with user identity...")

        # Server: include identity in sendRequest
        requestID = blpapi.CorrelationId(1)
        session.sendRequest(request, self.identity, requestID)

    def processMiscEvents(self, event):
        print("Processing %s event" % event.eventType())
        for msg in event:
            print("MESSAGE: %s" % (msg))


def main():
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
    while not bEnd:
        pass

    session.stop()


if __name__ == "__main__":
    print("Bloomberg - EMSX API Example - User Identity (Trading API Server)")
    print("")
    print("NOTE: Update d_user (EMRS ID) and d_ip (server IP) before running.")
    print("      This example only works with Trading API Server, not Desktop API.")
    print("")
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl+C pressed. Stopping...")
