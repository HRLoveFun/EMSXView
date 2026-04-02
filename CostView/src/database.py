"""
FillFetch Database Module
Manages SQL table to track fetch history with hash-based deduplication.
"""

import os
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from sqlalchemy import (
    create_engine, Column, String, DateTime, Integer, Float,
    UniqueConstraint, inspect, text
)
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class FillFetchHistory(Base):
    """SQL table to track fill fetch history."""
    __tablename__ = 'fill_fetch_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_date = Column(String(10), nullable=False, index=True)
    fetch_time = Column(String(30), nullable=False)
    import_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    row_count = Column(Integer, nullable=False)
    hash_value = Column(String(64), nullable=False, index=True)
    file_path = Column(String(500), nullable=True)
    
    __table_args__ = (
        UniqueConstraint('order_date', 'hash_value', name='uix_date_hash'),
    )


class FillFetchDatabase:
    """Database manager for FillFetch operations."""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.getenv('FILLFETCH_DB_PATH', './data/fill_fetch_history.db')
        
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.engine = create_engine(f'sqlite:///{self.db_path}', echo=False, future=True)
        self.Session = sessionmaker(bind=self.engine)
        self._init_tables()
        logger.info(f"Database initialized at: {self.db_path}")
    
    def _init_tables(self):
        Base.metadata.create_all(self.engine)
    
    def check_duplicate(self, order_date: str, hash_value: str) -> bool:
        """Check if a fetch record with same date and hash exists."""
        with self.Session() as session:
            existing = session.query(FillFetchHistory).filter_by(
                order_date=order_date, hash_value=hash_value
            ).first()
            if existing:
                logger.info(f"Duplicate found for {order_date} with hash {hash_value[:16]}...")
                return True
            return False
    
    def add_fetch_record(self, order_date: str, fetch_time: str, row_count: int,
                         hash_value: str, file_path: Optional[str] = None) -> FillFetchHistory:
        """Add a new fetch record to the database."""
        record = FillFetchHistory(
            order_date=order_date, fetch_time=fetch_time,
            import_timestamp=datetime.utcnow(), row_count=row_count,
            hash_value=hash_value, file_path=file_path
        )
        with self.Session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info(f"Added fetch record for {order_date}: {row_count} rows")
            return record
    
    def get_fetch_history(self, order_date: Optional[str] = None, limit: int = 100) -> List[FillFetchHistory]:
        """Get fetch history records."""
        with self.Session() as session:
            query = session.query(FillFetchHistory)
            if order_date:
                query = query.filter_by(order_date=order_date)
            return query.order_by(FillFetchHistory.import_timestamp.desc()).limit(limit).all()
    
    def get_latest_fetch(self, order_date: str) -> Optional[FillFetchHistory]:
        """Get the most recent fetch record for a specific date."""
        with self.Session() as session:
            return session.query(FillFetchHistory).filter_by(order_date=order_date) \
                .order_by(FillFetchHistory.import_timestamp.desc()).first()

    def delete_records_for_date(self, order_date: str) -> int:
        """Delete all fetch records for a specific date. Returns count deleted."""
        with self.Session() as session:
            count = session.query(FillFetchHistory).filter_by(
                order_date=order_date
            ).delete()
            session.commit()
            if count:
                logger.info(f"Deleted {count} existing record(s) for {order_date}")
            return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self.Session() as session:
            total_records = session.query(FillFetchHistory).count()
            total_rows = session.query(text('SUM(row_count)')).select_from(FillFetchHistory).scalar() or 0
            unique_dates = session.query(text('COUNT(DISTINCT order_date)')).select_from(FillFetchHistory).scalar() or 0
            latest = session.query(FillFetchHistory).order_by(FillFetchHistory.import_timestamp.desc()).first()
            return {
                'total_records': total_records, 'total_rows_fetched': total_rows,
                'unique_dates': unique_dates,
                'latest_fetch': latest.import_timestamp.isoformat() if latest else None,
                'database_path': str(self.db_path)
            }
    
    def close(self):
        self.engine.dispose()
        logger.info("Database connection closed")


def compute_data_hash(data: List[Dict[str, Any]]) -> str:
    """Compute SHA-256 hash of data for deduplication."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
