"""
Unit tests for FillFetch module.
"""

import os
import sys
import unittest
import tempfile
import shutil
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from database import FillFetchDatabase, compute_data_hash


class TestDatabase(unittest.TestCase):
    """Test database operations."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        self.db = FillFetchDatabase(str(self.db_path))
    
    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir)
    
    def test_compute_hash(self):
        """Test hash computation."""
        data = [{'a': 1, 'b': 2}, {'a': 3, 'b': 4}]
        hash1 = compute_data_hash(data)
        hash2 = compute_data_hash(data)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA-256 hex length
    
    def test_check_duplicate(self):
        """Test duplicate detection."""
        self.assertFalse(self.db.check_duplicate('2024-01-01', 'abc123'))
        
        self.db.add_fetch_record('2024-01-01', '00:00:00-23:59:59', 10, 'abc123')
        self.assertTrue(self.db.check_duplicate('2024-01-01', 'abc123'))
        self.assertFalse(self.db.check_duplicate('2024-01-02', 'abc123'))
    
    def test_get_stats(self):
        """Test statistics retrieval."""
        stats = self.db.get_stats()
        self.assertEqual(stats['total_records'], 0)
        
        self.db.add_fetch_record('2024-01-01', '00:00:00-23:59:59', 10, 'hash1')
        self.db.add_fetch_record('2024-01-02', '00:00:00-23:59:59', 20, 'hash2')
        
        stats = self.db.get_stats()
        self.assertEqual(stats['total_records'], 2)
        self.assertEqual(stats['total_rows_fetched'], 30)
        self.assertEqual(stats['unique_dates'], 2)


class TestHashComputation(unittest.TestCase):
    """Test hash computation logic."""
    
    def test_consistency(self):
        """Test that same data produces same hash."""
        data = [
            {'fill_id': 1, 'price': 100.5, 'shares': 100},
            {'fill_id': 2, 'price': 101.0, 'shares': 200}
        ]
        h1 = compute_data_hash(data)
        h2 = compute_data_hash(data)
        self.assertEqual(h1, h2)
    
    def test_order_independence(self):
        """Test that key order doesn't matter."""
        data1 = [{'a': 1, 'b': 2}]
        data2 = [{'b': 2, 'a': 1}]
        self.assertEqual(compute_data_hash(data1), compute_data_hash(data2))
    
    def test_different_data(self):
        """Test different data produces different hash."""
        data1 = [{'a': 1}]
        data2 = [{'a': 2}]
        self.assertNotEqual(compute_data_hash(data1), compute_data_hash(data2))


if __name__ == '__main__':
    unittest.main()
