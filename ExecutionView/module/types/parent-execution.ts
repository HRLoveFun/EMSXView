/**
 * Parent-child execution types — schedule-based algorithmic execution.
 *
 * P3-SRP: Extracted from types/index.ts.
 */

export type ScheduleType = 'TWAP' | 'VWAP' | 'POV' | 'IS' | 'MANUAL';
export type ExecutionStatus = 'PENDING' | 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'CANCELLED' | 'FAILED';
export type SliceStatus = 'PENDING' | 'SENT' | 'WORKING' | 'FILLED' | 'CANCELLED' | 'FAILED';

export interface ParentExecution {
  id: number;
  sequence: number;
  orderId: string;
  trader: string;
  scheduleType: ScheduleType;
  targetQuantity: number;
  filledQuantity: number;
  startTime: string | null;
  endTime: string | null;
  participationRate: number | null;
  urgency: string | null;
  benchmarkPrice: number | null;
  broker: string | null;
  strategyParams: Record<string, unknown> | null;
  status: ExecutionStatus;
  createdAt: string;
  updatedAt: string;
  slices: ChildSlice[];
}

export interface ChildSlice {
  id: number;
  parentId: number;
  sequence: number;
  routeId: number | null;
  sliceIndex: number;
  plannedQuantity: number;
  filledQuantity: number;
  scheduledStart: string | null;
  scheduledEnd: string | null;
  limitPrice: number | null;
  strategyParams: Record<string, unknown> | null;
  status: SliceStatus;
  createdAt: string;
  updatedAt: string;
}

export type SchedulerCommand = 'PAUSE' | 'RESUME' | 'CANCEL';

export interface CreateParentExecutionRequest {
  orderId: string;
  scheduleType: ScheduleType;
  targetQuantity: number;
  numSlices: number;
  startTime: string;
  endTime: string;
  participationRate?: number | null;
  volumeProfile?: number[] | null;
  broker?: string;
  urgency?: string;
  strategyParams?: Record<string, unknown>;
}

export interface ParentExecutionCommandRequest {
  command: SchedulerCommand;
}

export interface SchedulerStateResponse {
  parentId: number;
  status: ExecutionStatus;
  isRunning: boolean;
  currentSliceIndex: number;
  totalSlices: number;
  slicesSent: number;
  slicesFilled: number;
  slicesCancelled: number;
  targetQuantity: number;
  filledQuantity: number;
  createdAt: string;
  updatedAt: string;
}

export interface ActiveExecutionSummary {
  parentId: number;
  orderId: string;
  scheduleType: ScheduleType;
  targetQuantity: number;
  status: ExecutionStatus;
  trader: string;
}
