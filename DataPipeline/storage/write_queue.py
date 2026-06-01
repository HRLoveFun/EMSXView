"""Asynchronous batch write queue for high-throughput ingestion paths.

Decouples data production from persistence for agg_fills_10s, fill_bdib,
and other high-frequency write tables. Uses a producer-consumer model with
per-database worker threads, batched transactions, and backpressure control.

Usage::

    from DataPipeline.storage.write_queue import WriteQueue, WriteQueueConfig
    from DataPipeline.storage.connection import ConnectionManager

    mgr = ConnectionManager()
    wq = WriteQueue(lambda db: mgr.get_connection(db, AccessTier.WRITE))
    wq.start(["processed_fills", "fill_bdib"])

    wq.enqueue("processed_fills", "INSERT INTO agg_fills_10s VALUES (?,?,?)",
               params_list)

    # Graceful shutdown
    wq.stop()
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

Param = Union[tuple, List[tuple]]


@dataclass
class WriteTask:
    db_key: str
    sql: str
    params: Param
    callback: Optional[Callable] = None
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class WriteQueueConfig:
    max_queue_size: int = 10_000
    batch_size: int = 500
    flush_interval_sec: float = 0.5
    backpressure_threshold: float = 0.8


class WriteQueue:

    def __init__(
        self,
        get_connection: Callable[[str], sqlite3.Connection],
        config: Optional[WriteQueueConfig] = None,
    ) -> None:
        self._get_conn = get_connection
        self._config = config or WriteQueueConfig()
        self._queues: Dict[str, queue.Queue[WriteTask]] = {}
        self._workers: Dict[str, threading.Thread] = {}
        self._running = False
        self._lock = threading.Lock()

    def start(self, db_keys: List[str]) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            for db_key in db_keys:
                self._queues[db_key] = queue.Queue(maxsize=self._config.max_queue_size)
                worker = threading.Thread(
                    target=self._worker_loop,
                    args=(db_key,),
                    daemon=True,
                    name=f"writeq-{db_key}",
                )
                self._workers[db_key] = worker
                worker.start()
            logger.info("WriteQueue started for %d databases", len(db_keys))

    def stop(self, timeout: float = 10.0) -> None:
        with self._lock:
            self._running = False
        for db_key, q in list(self._queues.items()):
            try:
                q.put(
                    WriteTask(db_key="__SHUTDOWN__", sql="", params=()),
                    timeout=1.0,
                )
            except queue.Full:
                pass
        for worker in self._workers.values():
            worker.join(timeout=timeout)
        self._queues.clear()
        self._workers.clear()
        logger.info("WriteQueue stopped")

    def enqueue(
        self,
        db_key: str,
        sql: str,
        params: Param,
        callback: Optional[Callable] = None,
    ) -> bool:
        q = self._queues.get(db_key)
        if q is None:
            raise ValueError(f"No write queue for db_key={db_key}")

        if q.qsize() >= self._config.max_queue_size * self._config.backpressure_threshold:
            logger.warning(
                "WriteQueue backpressure: %s queue=%d/%d",
                db_key, q.qsize(), self._config.max_queue_size,
            )
            return False

        task = WriteTask(db_key=db_key, sql=sql, params=params, callback=callback)
        q.put(task)
        return True

    def qsize(self, db_key: str) -> int:
        q = self._queues.get(db_key)
        return q.qsize() if q else 0

    def all_qsizes(self) -> Dict[str, int]:
        return {k: v.qsize() for k, v in self._queues.items()}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _worker_loop(self, db_key: str) -> None:
        q = self._queues[db_key]
        batch: List[WriteTask] = []
        last_flush = time.monotonic()

        while self._running:
            try:
                task = q.get(timeout=self._config.flush_interval_sec)
            except queue.Empty:
                task = None

            if task is not None:
                if task.db_key == "__SHUTDOWN__":
                    break
                batch.append(task)

            should_flush = (
                len(batch) >= self._config.batch_size
                or (batch and time.monotonic() - last_flush > self._config.flush_interval_sec)
            )

            if should_flush:
                self._flush_batch(db_key, batch)
                batch.clear()
                last_flush = time.monotonic()

        if batch:
            self._flush_batch(db_key, batch)

    def _flush_batch(self, db_key: str, batch: List[WriteTask]) -> None:
        if not batch:
            return

        conn = self._get_conn(db_key)
        start = time.monotonic()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for task in batch:
                if isinstance(task.params, list):
                    conn.executemany(task.sql, task.params)
                else:
                    conn.execute(task.sql, task.params)
            conn.commit()
            elapsed = (time.monotonic() - start) * 1000
            logger.debug(
                "WriteQueue flush %s: %d tasks in %.1fms",
                db_key, len(batch), elapsed,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception(
                "WriteQueue flush failed for %s (%d tasks)", db_key, len(batch)
            )
            for task in batch:
                if task.callback:
                    try:
                        task.callback(None, "flush_failed")
                    except Exception:
                        pass
        else:
            for task in batch:
                if task.callback:
                    try:
                        task.callback(len(batch), None)
                    except Exception:
                        pass
        finally:
            conn.close()
