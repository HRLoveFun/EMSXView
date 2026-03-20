# cancel_order.py
# Bloomberg EMSX API - CancelOrderEx Request
# Source: EMSX-API-Complete-Guide.md - "CancelOrderEx" section
# Quick Reference: Section 4.1 Order Management

import blpapi
import sys


SESSION_STARTED         = blpapi.Name("SessionStarted")
SESSION_STARTUP_FAILURE = blpapi.Name("SessionStartupFailure")
SERVICE_OPENED          = blpapi.Name("ServiceOpened")
SERVICE_OPEN_FAILURE    = blpapi.Name("ServiceOpenFailure")
ERROR_INFO              = blpapi.Name("ErrorInfo")
CANCEL_ORDER_EX         = blpapi.Name("CancelOrderEx")

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

                request = service.createRequest("CancelOrderEx")

                # Mandatory: append one or more order sequence numbers
                request.append("EMSX_SEQUENCE", 4116148)
                # request.append("EMSX_SEQUENCE", 4116149)  # Can cancel multiple

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
                elif msg.messageType() == CANCEL_ORDER_EX:
                    status = msg.getElementAsInteger("STATUS")
                    message = msg.getElementAsString("MESSAGE")
                    print ("STATUS: %d\tMESSAGE: %s" % (status,message))

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
    print ("Bloomberg - EMSX API Example - CancelOrderEx")
    try:
        main()
    except KeyboardInterrupt:
        print ("Ctrl+C pressed. Stopping...")
