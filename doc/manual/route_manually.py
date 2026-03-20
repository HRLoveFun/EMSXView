# route_manually.py
# Bloomberg EMSX API - RouteManuallyEx Request
# Source: EMSX-API-Complete-Guide.md - "RouteManuallyEx" section
# For phone orders where placement is external to EMSX API

import blpapi
import sys


SESSION_STARTED         = blpapi.Name("SessionStarted")
SESSION_STARTUP_FAILURE = blpapi.Name("SessionStartupFailure")
SERVICE_OPENED          = blpapi.Name("ServiceOpened")
SERVICE_OPEN_FAILURE    = blpapi.Name("ServiceOpenFailure")
ERROR_INFO              = blpapi.Name("ErrorInfo")
ROUTE_MANUALLY          = blpapi.Name("RouteManuallyEx")

d_service="//blp/emapisvc_beta"
d_host="localhost"
d_port=8194
bEnd=False


class SessionEventHandler():

    def processEvent(self, event, session):
        try:
            if event.eventType() == blpapi.Event.SESSION_STATUS:
                self.processSessionStatusEvent(event,session)
            elif event.eventType() == blpapi.Event.SERVICE_STATUS:
                self.processServiceStatusEvent(event,session)
            elif event.eventType() == blpapi.Event.RESPONSE:
                self.processResponseEvent(event)
            else:
                self.processMiscEvents(event)
        except:
            print ("Exception:  %s" % sys.exc_info()[0])
        return False

    def processSessionStatusEvent(self,event,session):
        print ("Processing SESSION_STATUS event")
        for msg in event:
            if msg.messageType() == SESSION_STARTED:
                print ("Session started...")
                session.openServiceAsync(d_service)
            elif msg.messageType() == SESSION_STARTUP_FAILURE:
                print("Error: Session startup failed", file=sys.stderr)
            else:
                print (msg)

    def processServiceStatusEvent(self,event,session):
        print ("Processing SERVICE_STATUS event")
        for msg in event:
            if msg.messageType() == SERVICE_OPENED:
                print ("Service opened...")

                service = session.getService(d_service)

                request = service.createRequest("RouteManuallyEx")

                # Mandatory fields
                request.set("EMSX_SEQUENCE", 4113517)
                request.set("EMSX_AMOUNT", 500)
                request.set("EMSX_BROKER", "BB")
                request.set("EMSX_HAND_INSTRUCTION", "ANY")
                request.set("EMSX_ORDER_TYPE", "MKT")
                request.set("EMSX_TICKER", "AAPL US Equity")
                request.set("EMSX_TIF", "DAY")

                # Optional fields
                #request.set("EMSX_ACCOUNT","TestAccount")
                #request.set("EMSX_BOOKNAME","BookName")
                #request.set("EMSX_CFD_FLAG", "1")
                #request.set("EMSX_CLEARING_ACCOUNT", "ClrAccName")
                #request.set("EMSX_CLEARING_FIRM", "FirmName")
                #request.set("EMSX_EXEC_INSTRUCTION", "Drop down values from EMSX Ticket")
                #request.set("EMSX_GET_WARNINGS", "0")
                #request.set("EMSX_GTD_DATE", "20170105")
                #request.set("EMSX_LIMIT_PRICE", 123.45)
                #request.set("EMSX_LOCATE_BROKER", "BMTB")
                #request.set("EMSX_LOCATE_ID", "SomeID")
                #request.set("EMSX_LOCATE_REQ", "Y")
                #request.set("EMSX_NOTES", "Some notes")
                #request.set("EMSX_ODD_LOT", "0")
                #request.set("EMSX_P_A", "P")
                #request.set("EMSX_RELEASE_TIME", 34341)
                #request.set("EMSX_REQUEST_SEQ", 1001)
                #request.set("EMSX_ROUTE_REF_ID", "UniqueRef")
                #request.set("EMSX_STOP_PRICE", 123.5)
                #request.set("EMSX_TRADER_UUID", 1234567)
                #request.set("EMSX_MANUAL_ORD_INDICATOR", False)

                print ("Request: %s" % request.toString())

                self.requestID = blpapi.CorrelationId()
                session.sendRequest(request, correlationId=self.requestID )

            elif msg.messageType() == SERVICE_OPEN_FAILURE:
                print("Error: Service failed to open", file=sys.stderr)

    def processResponseEvent(self, event):
        print ("Processing RESPONSE event")
        for msg in event:
            print ("MESSAGE: %s" % msg.toString())
            print ("CORRELATION ID: %d" % msg.correlationIds()[0].value())

            if msg.correlationIds()[0].value() == self.requestID.value():
                print ("MESSAGE TYPE: %s" % msg.messageType())
                if msg.messageType() == ERROR_INFO:
                    errorCode = msg.getElementAsInteger("ERROR_CODE")
                    errorMessage = msg.getElementAsString("ERROR_MESSAGE")
                    print ("ERROR CODE: %d\tERROR MESSAGE: %s" % (errorCode,errorMessage))
                elif msg.messageType() == ROUTE_MANUALLY:
                    emsx_sequence = msg.getElementAsInteger("EMSX_SEQUENCE")
                    emsx_route_id = msg.getElementAsInteger("EMSX_ROUTE_ID")
                    message = msg.getElementAsString("MESSAGE")
                    print ("EMSX_SEQUENCE: %d\tEMSX_ROUTE_ID: %d\tMESSAGE: %s" % (emsx_sequence,emsx_route_id,message))

                global bEnd
                bEnd = True

    def processMiscEvents(self, event):
        print ("Processing " + event.eventType() + " event")
        for msg in event:
            print ("MESSAGE: %s" % (msg.tostring()))


def main():
    sessionOptions = blpapi.SessionOptions()
    sessionOptions.setServerHost(d_host)
    sessionOptions.setServerPort(d_port)

    print ("Connecting to %s:%d" % (d_host,d_port))

    eventHandler = SessionEventHandler()
    session = blpapi.Session(sessionOptions, eventHandler.processEvent)

    if not session.startAsync():
        print ("Failed to start session.")
        return

    global bEnd
    while bEnd==False:
        pass

    session.stop()

if __name__ == "__main__":
    print ("Bloomberg - EMSX API Example - RouteManuallyEx")
    try:
        main()
    except KeyboardInterrupt:
        print ("Ctrl+C pressed. Stopping...")
