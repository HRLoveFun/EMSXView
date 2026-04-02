"""
Unit tests for Secure Configuration module.
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from secure_config import (
    SecureConfigManager, UUIDConfig, CredentialNotFoundError,
    ConfigurationError, get_config_manager, get_uuid
)


class TestUUIDConfig(unittest.TestCase):
    """Test UUIDConfig dataclass."""
    
    def test_valid_uuid(self):
        """Test creating valid UUIDConfig."""
        config = UUIDConfig(uuid=12345)
        self.assertEqual(config.uuid, 12345)
        self.assertIsNone(config.name)
    
    def test_invalid_uuid_zero(self):
        """Test that zero UUID raises error."""
        with self.assertRaises(ValueError):
            UUIDConfig(uuid=0)
    
    def test_invalid_uuid_negative(self):
        """Test that negative UUID raises error."""
        with self.assertRaises(ValueError):
            UUIDConfig(uuid=-1)
    
    def test_invalid_uuid_string(self):
        """Test that string UUID raises error."""
        with self.assertRaises(ValueError):
            UUIDConfig(uuid="12345")


class TestSecureConfigManager(unittest.TestCase):
    """Test SecureConfigManager functionality."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SecureConfigManager(self.temp_dir)
        # Clear any existing env vars
        self._clear_env_vars()
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        self._clear_env_vars()
    
    def _clear_env_vars(self):
        """Clear UUID environment variables."""
        for var in ['EMSX_UUID', 'BLOOMBERG_UUID']:
            if var in os.environ:
                del os.environ[var]
    
    def test_load_from_env_primary(self):
        """Test loading UUID from primary env var."""
        os.environ['EMSX_UUID'] = '12345'
        config = self.manager._load_from_env()
        self.assertIsNotNone(config)
        self.assertEqual(config.uuid, 12345)
        self.assertEqual(config.description, 'EMSX_UUID')
    
    def test_load_from_env_alt(self):
        """Test loading UUID from alternate env var."""
        os.environ['BLOOMBERG_UUID'] = '67890'
        config = self.manager._load_from_env()
        self.assertIsNotNone(config)
        self.assertEqual(config.uuid, 67890)
    
    def test_load_from_env_invalid(self):
        """Test handling invalid env var value."""
        os.environ['EMSX_UUID'] = 'not_a_number'
        config = self.manager._load_from_env()
        self.assertIsNone(config)
    
    def test_save_and_load_credentials(self):
        """Test saving and loading from credentials file."""
        self.manager.save_credentials(54321, name="test")
        config = self.manager._load_from_file()
        self.assertIsNotNone(config)
        self.assertEqual(config.uuid, 54321)
    
    def test_check_duplicate_detection(self):
        """Test that credentials file is detected."""
        self.assertFalse(self.manager._credentials_file.exists())
        self.manager.save_credentials(11111)
        self.assertTrue(self.manager._credentials_file.exists())
    
    def test_caching(self):
        """Test that UUID is cached after first load."""
        os.environ['EMSX_UUID'] = '99999'
        
        # First call should load from env
        config1 = self.manager.get_uuid(allow_prompt=False)
        self.assertEqual(config1.uuid, 99999)
        
        # Change env var
        os.environ['EMSX_UUID'] = '11111'
        
        # Second call should return cached value
        config2 = self.manager.get_uuid(allow_prompt=False)
        self.assertEqual(config2.uuid, 99999)  # Cached, not 11111
        
        # Clear cache and reload
        self.manager.clear_cache()
        config3 = self.manager.get_uuid(allow_prompt=False)
        self.assertEqual(config3.uuid, 11111)  # Now from new env var
    
    def test_required_raises_exception(self):
        """Test that required=True raises when UUID not found."""
        with self.assertRaises(CredentialNotFoundError):
            self.manager.get_uuid(allow_prompt=False, required=True)
    
    def test_not_required_returns_none(self):
        """Test that required=False returns None when not found."""
        config = self.manager.get_uuid(allow_prompt=False, required=False)
        self.assertIsNone(config)
    
    def test_external_provider(self):
        """Test external credential provider."""
        mock_provider = MagicMock(return_value=77777)
        self.manager.set_external_provider(mock_provider)
        
        config = self.manager._load_from_external()
        self.assertIsNotNone(config)
        self.assertEqual(config.uuid, 77777)
        mock_provider.assert_called_once()
    
    def test_validate_setup_no_uuid(self):
        """Test validation when no UUID configured."""
        results = self.manager.validate_setup()
        self.assertFalse(results['uuid_loadable'])
        self.assertFalse(results['env_var_set'])
        self.assertIn('UUID not found', results['errors'][0])
    
    def test_validate_setup_with_uuid(self):
        """Test validation when UUID is configured."""
        os.environ['EMSX_UUID'] = '55555'
        results = self.manager.validate_setup()
        self.assertTrue(results['uuid_loadable'])
        self.assertTrue(results['env_var_set'])
        self.assertEqual(results['uuid_source'], 'EMSX_UUID')


class TestGlobalFunctions(unittest.TestCase):
    """Test module-level convenience functions."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._clear_env_vars()
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        self._clear_env_vars()
    
    def _clear_env_vars(self):
        for var in ['EMSX_UUID', 'BLOOMBERG_UUID']:
            if var in os.environ:
                del os.environ[var]
    
    @patch('secure_config._config_manager', None)
    def test_get_config_manager_singleton(self):
        """Test that get_config_manager returns singleton."""
        manager1 = get_config_manager(self.temp_dir)
        manager2 = get_config_manager()
        self.assertIs(manager1, manager2)
    
    @patch('secure_config._config_manager', None)
    def test_get_uuid_convenience(self):
        """Test get_uuid convenience function."""
        os.environ['EMSX_UUID'] = '44444'
        config = get_uuid(allow_prompt=False)
        self.assertEqual(config.uuid, 44444)


if __name__ == '__main__':
    unittest.main()
