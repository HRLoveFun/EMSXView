/** Route status badge (A14/229). Extracted verbatim from RouteTable.tsx. */

import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  MinusCircle,
  XCircle,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export const getStatusBadge = (status: string) => {
  switch (status) {
    case 'SENT':       return <Badge variant="outline" className="status-badge status-new gap-1"><AlertCircle className="h-3 w-3" />Sent</Badge>;
    case 'WORKING':    return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />Working</Badge>;
    case 'PARTFILLED':
    case 'PARTFILL':   return <Badge variant="outline" className="status-badge status-partial gap-1"><MinusCircle className="h-3 w-3" />PartFill</Badge>;
    case 'FILLED':     return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Filled</Badge>;
    case 'CANCEL':     return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Cancel</Badge>;
    case 'CXLREQ':     return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />CxlReq</Badge>;
    case 'CXLREJ':     return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />CxlRej</Badge>;
    case 'CXLREP':     return <Badge variant="outline" className="status-badge status-working gap-1"><Loader2 className="h-3 w-3 animate-spin" />Replacing</Badge>;
    case 'CXLRPRQ':    return <Badge variant="outline" className="status-badge status-working gap-1"><Loader2 className="h-3 w-3 animate-spin" />Replacing</Badge>;
    case 'CXLRPRJ':    return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />CxlRprJ</Badge>;
    case 'REJECTED':   return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Rejected</Badge>;
    case 'DONE':       return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Done</Badge>;
    case 'QUEUED':     return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />Queued</Badge>;
    case 'HOLD':       return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />Hold</Badge>;
    case 'BUST':       return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Bust</Badge>;
    case 'CORRECTED':  return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Corrected</Badge>;
    case 'REPPEN':     return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />RepPen</Badge>;
    case 'ROUTE-ERR':  return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Error</Badge>;
    case 'OMS-PEND':   return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />OmsPend</Badge>;
    case 'A-SENT':     return <Badge variant="outline" className="status-badge status-new gap-1"><AlertCircle className="h-3 w-3" />A-Sent</Badge>;
    case 'ALLOCATED':  return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Allocated</Badge>;
    case 'OA-SENT':    return <Badge variant="outline" className="status-badge status-new gap-1"><AlertCircle className="h-3 w-3" />OA-Sent</Badge>;
    default:           return <Badge variant="outline" className="status-badge gap-1">{status}</Badge>;
  }
};
