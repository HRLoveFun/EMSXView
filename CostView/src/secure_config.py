"""
Secure Configuration Module for FillFetch

Manages sensitive configuration like UUIDs without hardcoded values.
Supports environment variables, secure credential files, and keyring integration.
"""

import os
import json
import logging
import getpass
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration cannot be loaded."""
    pass


class CredentialNotFoundError(ConfigurationError):
    """Raised when a required credential is not found."""
    pass


@dataclass(frozen=True)
class UUIDConfig:
    """Immutable UUID configuration."""
    uuid: int
    name: Optional[str] = None
    description: Optional[str] = None
    
    def __post_init__(self):
        if not isinstance(self.uuid, int) or self.uuid <= 0:
            raise ValueError(f"UUID must be a positive integer, got {self.uuid}")


class SecureConfigManager:
    """
    Secure configuration manager that loads UUIDs from various sources
    without hardcoded defaults in function signatures.
    
    Priority order:
    1. Environment variables
    2. Secure credential file (encrypted or permission-protected)
    3. Interactive prompt (for CLI usage)
    4. External credential provider (keyring, vault, etc.)
    """
    
    ENV_VAR_NAME = "EMSX_UUID"
    ENV_VAR_NAME_ALT = "BLOOMBERG_UUID"
    CREDENTIALS_FILE = "credentials.json"
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize the secure config manager.
        
        Args:
            config_dir: Directory for configuration files.
                       If None, uses ~/.config/fillfetch/
        """
        if config_dir:
            self.config_dir = Path(config_dir).expanduser().resolve()
        else:
            self.config_dir = Path.home() / ".config" / "fillfetch"
        
        self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._credentials_file = self.config_dir / self.CREDENTIALS_FILE
        self._uuid_cache: Optional[UUIDConfig] = None
        self._external_provider: Optional[Callable[[], Optional[int]]] = None
        
        logger.debug(f"SecureConfigManager initialized: {self.config_dir}")
    
    def set_external_provider(self, provider: Callable[[], Optional[int]]):
        """
        Set an external credential provider (e.g., keyring, HashiCorp Vault).
        
        Args:
            provider: Callable that returns UUID or None
        """
        self._external_provider = provider
    
    def _load_from_env(self) -> Optional[UUIDConfig]:
        """Load UUID from environment variables."""
        for env_var in [self.ENV_VAR_NAME, self.ENV_VAR_NAME_ALT]:
            value = os.getenv(env_var)
            if value:
                try:
                    uuid = int(value)
                    logger.debug(f"Loaded UUID from {env_var}")
                    return UUIDConfig(uuid=uuid, name="environment", description=env_var)
                except ValueError:
                    logger.warning(f"Invalid UUID in {env_var}: {value}")
        return None
    
    def _load_from_file(self) -> Optional[UUIDConfig]:
        """Load UUID from secure credentials file."""
        if not self._credentials_file.exists():
            return None
        
        try:
            # Check file permissions (should be user-readable only)
            stat = self._credentials_file.stat()
            mode = stat.st_mode & 0o777
            if mode != 0o600:
                logger.warning(
                    f"Credentials file has permissions {oct(mode)}, expected 0o600. "
                    "Run: chmod 600 {self._credentials_file}"
                )
            
            with open(self._credentials_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            uuid = data.get('uuid')
            if uuid is not None:
                logger.debug("Loaded UUID from credentials file")
                return UUIDConfig(
                    uuid=int(uuid),
                    name=data.get('name'),
                    description="credentials_file"
                )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Error loading credentials file: {e}")
        
        return None
    
    def _load_from_external(self) -> Optional[UUIDConfig]:
        """Load UUID from external provider (keyring, vault, etc.)."""
        if self._external_provider:
            try:
                uuid = self._external_provider()
                if uuid:
                    logger.debug("Loaded UUID from external provider")
                    return UUIDConfig(uuid=uuid, name="external", description="external_provider")
            except Exception as e:
                logger.error(f"External provider error: {e}")
        return None
    
    def _prompt_interactive(self) -> UUIDConfig:
        """Prompt user for UUID interactively."""
        print("\n" + "=" * 50)
        print("FillFetch - UUID Configuration Required")
        print("=" * 50)
        print("\nNo UUID found in environment or credential files.")
        print("Please enter your Bloomberg UUID.\n")
        
        while True:
            try:
                uuid_input = input("UUID: ").strip()
                uuid = int(uuid_input)
                if uuid <= 0:
                    raise ValueError("UUID must be positive")
                
                print(f"\nUsing UUID: {uuid}")
                save = input("Save to credentials file for future use? [Y/n]: ").strip().lower()
                
                config = UUIDConfig(uuid=uuid, name="interactive", description="user_input")
                
                if save in ('', 'y', 'yes'):
                    self.save_credentials(uuid)
                
                return config
                
            except ValueError as e:
                print(f"Invalid input: {e}. Please enter a positive integer.")
    
    def get_uuid(self, allow_prompt: bool = True, required: bool = True) -> Optional[UUIDConfig]:
        """
        Get UUID from available sources.
        
        Args:
            allow_prompt: If True, prompt user interactively when not found
            required: If True, raise exception when UUID not found
            
        Returns:
            UUIDConfig or None if not required and not found
            
        Raises:
            CredentialNotFoundError: If required=True and UUID not found
        """
        # Check cache first
        if self._uuid_cache is not None:
            return self._uuid_cache
        
        # Try sources in priority order
        sources = [
            ("environment", self._load_from_env),
            ("external_provider", self._load_from_external),
            ("credentials_file", self._load_from_file),
        ]
        
        for source_name, loader in sources:
            try:
                config = loader()
                if config:
                    self._uuid_cache = config
                    logger.info(f"UUID loaded from {source_name}")
                    return config
            except Exception as e:
                logger.debug(f"Failed to load from {source_name}: {e}")
        
        # Interactive prompt as last resort
        if allow_prompt:
            try:
                config = self._prompt_interactive()
                self._uuid_cache = config
                return config
            except (EOFError, KeyboardInterrupt):
                logger.warning("Interactive prompt cancelled")
        
        if required:
            raise CredentialNotFoundError(
                f"UUID not found. Set {self.ENV_VAR_NAME} environment variable "
                f"or run with interactive mode enabled."
            )
        
        return None
    
    def save_credentials(self, uuid: int, name: Optional[str] = None):
        """
        Save UUID to secure credentials file.
        
        Args:
            uuid: The UUID to save
            name: Optional name/description for the credential
        """
        data = {
            "uuid": uuid,
            "name": name or "default",
            "saved_at": str(Path().home())  # Don't use datetime, avoid extra imports
        }
        
        with open(self._credentials_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Set restrictive permissions (user read/write only)
        os.chmod(self._credentials_file, 0o600)
        
        logger.info(f"Credentials saved to {self._credentials_file}")
    
    def clear_cache(self):
        """Clear the UUID cache."""
        self._uuid_cache = None
        logger.debug("UUID cache cleared")
    
    def validate_setup(self) -> Dict[str, Any]:
        """
        Validate the configuration setup and report status.
        
        Returns:
            Dictionary with validation results
        """
        results = {
            "config_dir": str(self.config_dir),
            "config_dir_exists": self.config_dir.exists(),
            "config_dir_permissions": None,
            "env_var_set": bool(os.getenv(self.ENV_VAR_NAME) or os.getenv(self.ENV_VAR_NAME_ALT)),
            "credentials_file_exists": self._credentials_file.exists(),
            "credentials_file_permissions": None,
            "external_provider_set": self._external_provider is not None,
            "uuid_loadable": False,
            "uuid_source": None,
            "errors": []
        }
        
        # Check directory permissions
        if self.config_dir.exists():
            try:
                stat = self.config_dir.stat()
                results["config_dir_permissions"] = oct(stat.st_mode & 0o777)
            except Exception as e:
                results["errors"].append(f"Cannot stat config dir: {e}")
        
        # Check credentials file permissions
        if self._credentials_file.exists():
            try:
                stat = self._credentials_file.stat()
                results["credentials_file_permissions"] = oct(stat.st_mode & 0o777)
            except Exception as e:
                results["errors"].append(f"Cannot stat credentials file: {e}")
        
        # Try to load UUID
        try:
            config = self.get_uuid(allow_prompt=False, required=False)
            if config:
                results["uuid_loadable"] = True
                results["uuid_source"] = config.description
            else:
                results["errors"].append("UUID not found in any source")
        except Exception as e:
            results["errors"].append(f"Error loading UUID: {e}")
        
        return results


# Global instance for convenience
_config_manager: Optional[SecureConfigManager] = None


def get_config_manager(config_dir: Optional[str] = None) -> SecureConfigManager:
    """Get or create the global SecureConfigManager instance."""
    global _config_manager
    if _config_manager is None or config_dir is not None:
        _config_manager = SecureConfigManager(config_dir)
    return _config_manager


def get_uuid(allow_prompt: bool = True, required: bool = True) -> Optional[UUIDConfig]:
    """Convenience function to get UUID using global config manager."""
    return get_config_manager().get_uuid(allow_prompt=allow_prompt, required=required)


def configure_logging(level: str = "INFO"):
    """Configure logging with appropriate format."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


if __name__ == "__main__":
    # CLI for setup and validation
    import argparse
    
    parser = argparse.ArgumentParser(description="Secure Config Manager")
    parser.add_argument("--validate", action="store_true", help="Validate configuration")
    parser.add_argument("--setup", action="store_true", help="Interactive setup")
    parser.add_argument("--config-dir", type=str, help="Configuration directory")
    
    args = parser.parse_args()
    configure_logging("INFO")
    
    manager = SecureConfigManager(args.config_dir)
    
    if args.validate:
        print("\nValidating configuration...")
        results = manager.validate_setup()
        for key, value in results.items():
            print(f"  {key}: {value}")
    
    elif args.setup:
        print("\nRunning interactive setup...")
        try:
            config = manager.get_uuid(allow_prompt=True, required=True)
            print(f"\n✓ UUID configured: {config.uuid}")
            print(f"  Source: {config.description}")
        except CredentialNotFoundError as e:
            print(f"\n✗ Setup failed: {e}")
            exit(1)
    
    else:
        parser.print_help()
