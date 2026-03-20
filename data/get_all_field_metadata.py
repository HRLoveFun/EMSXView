"""
Bloomberg EMSX API — GetAllFieldMetaData
Fetches all available EMSX fields and their metadata.
Uses synchronous session (simpler than async for a one-shot request).
"""

import blpapi
import csv
import sys
from datetime import datetime

SERVICES = ["//blp/emapisvc", "//blp/emapisvc_beta"]
HOST = "localhost"
PORT = 8194


def main():
    print(f"Bloomberg EMSX — GetAllFieldMetaData  ({datetime.now():%Y-%m-%d %H:%M:%S})")
    print(f"Connecting to {HOST}:{PORT} ...")

    opts = blpapi.SessionOptions()
    opts.setServerHost(HOST)
    opts.setServerPort(PORT)

    session = blpapi.Session(opts)
    if not session.start():
        print("ERROR: Failed to start Bloomberg session", file=sys.stderr)
        return 1

    # Open EMSX service (try production first, then beta)
    service = None
    svc_name = None
    for s in SERVICES:
        if session.openService(s):
            service = session.getService(s)
            svc_name = s
            print(f"Opened service: {s}")
            break
        else:
            print(f"  Could not open {s}, trying next...")

    if not service:
        print("ERROR: Failed to open any EMSX service", file=sys.stderr)
        session.stop()
        return 1

    # Create and send GetAllFieldMetaData request
    request = service.createRequest("GetAllFieldMetaData")
    print(f"Sending request: GetAllFieldMetaData")
    cid = blpapi.CorrelationId(1)
    session.sendRequest(request, correlationId=cid)

    # Collect response
    fields = []
    done = False
    while not done:
        event = session.nextEvent(10000)  # 10s timeout
        etype = event.eventType()

        if etype in (blpapi.Event.PARTIAL_RESPONSE, blpapi.Event.RESPONSE):
            for msg in event:
                mtype = str(msg.messageType())
                if mtype == "ErrorInfo":
                    code = msg.getElementAsInteger("ERROR_CODE")
                    text = msg.getElementAsString("ERROR_MESSAGE")
                    print(f"ERROR from Bloomberg: [{code}] {text}", file=sys.stderr)
                elif mtype == "GetAllFieldMetaData":
                    md = msg.getElement("MetaData")
                    for e in md.values():
                        rec = {
                            "EMSX_FIELD_NAME": e.getElementAsString("EMSX_FIELD_NAME"),
                            "EMSX_DISP_NAME":  e.getElementAsString("EMSX_DISP_NAME"),
                            "EMSX_TYPE":       e.getElementAsString("EMSX_TYPE"),
                            "EMSX_LEVEL":      e.getElementAsInteger("EMSX_LEVEL"),
                            "EMSX_LEN":        e.getElementAsInteger("EMSX_LEN"),
                        }
                        fields.append(rec)
                else:
                    print(f"Unexpected message type: {mtype}")
                    print(msg.toString())

            if etype == blpapi.Event.RESPONSE:
                done = True

        elif etype == blpapi.Event.TIMEOUT:
            print("TIMEOUT waiting for response", file=sys.stderr)
            done = True

    session.stop()

    if not fields:
        print("No field metadata returned.")
        return 1

    # Print summary to console
    print(f"\n{'='*80}")
    print(f"Total fields: {len(fields)}")
    print(f"{'='*80}")
    print(f"{'FIELD_NAME':<40} {'DISP_NAME':<40} {'TYPE':<12} {'LEVEL':>5} {'LEN':>5}")
    print(f"{'-'*40} {'-'*40} {'-'*12} {'-'*5} {'-'*5}")
    for f in fields:
        print(f"{f['EMSX_FIELD_NAME']:<40} {f['EMSX_DISP_NAME']:<40} {f['EMSX_TYPE']:<12} {f['EMSX_LEVEL']:>5} {f['EMSX_LEN']:>5}")

    # Also write to CSV for easy reference
    csv_path = "emsx_field_metadata.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["EMSX_FIELD_NAME", "EMSX_DISP_NAME", "EMSX_TYPE", "EMSX_LEVEL", "EMSX_LEN"])
        writer.writeheader()
        writer.writerows(fields)
    print(f"\nCSV saved to: {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
