"""
Example: Secure UUID Usage in FillFetch

This example demonstrates how FillFetch securely manages UUIDs
without any hardcoded values in the codebase.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from datetime import date
from secure_config import get_config_manager, get_uuid, CredentialNotFoundError
from fill_fetch import FillFetch, resolve_uuid


def example_1_basic_usage():
    """Example 1: UUID auto-loaded from secure configuration."""
    print("=" * 60)
    print("Example 1: Auto-load UUID from secure config")
    print("=" * 60)
    
    try:
        # UUID is loaded automatically from env/credentials file
        # No hardcoded value needed!
        config = get_config_manager().get_uuid(allow_prompt=False)
        print(f"✓ UUID loaded: {config.uuid}")
        print(f"  Source: {config.description}")
        print(f"  Name: {config.name or 'N/A'}")
    except CredentialNotFoundError as e:
        print(f"✗ UUID not found: {e}")
        print("  Run: python -m src --setup-config")


def example_2_explicit_override():
    """Example 2: Explicit UUID overrides configuration."""
    print("\n" + "=" * 60)
    print("Example 2: Explicit UUID (overrides config)")
    print("=" * 60)
    
    # When you explicitly pass UUID, it takes precedence
    explicit_uuid = 99999  # This would normally come from user input
    resolved = resolve_uuid(uuid_arg=explicit_uuid, allow_prompt=False)
    print(f"✓ Using explicit UUID: {resolved}")


def example_3_validation():
    """Example 3: Validate configuration setup."""
    print("\n" + "=" * 60)
    print("Example 3: Validate configuration")
    print("=" * 60)
    
    manager = get_config_manager()
    results = manager.validate_setup()
    
    print("Configuration Status:")
    for key, value in results.items():
        icon = "✓" if value in [True, 'True'] else "✗" if value in [False, 'False'] else "•"
        print(f"  {icon} {key}: {value}")


def example_4_fetch_integration():
    """Example 4: Using with FillFetch (UUID auto-loaded)."""
    print("\n" + "=" * 60)
    print("Example 4: FillFetch with auto-loaded UUID")
    print("=" * 60)
    
    try:
        fetcher = FillFetch()
        
        # UUID is loaded from secure config automatically
        # No need to pass it explicitly!
        print("FillFetch initialized")
        print("UUID will be loaded from secure configuration when fetch_day() is called")
        
        # Show current config status
        try:
            config = get_config_manager().get_uuid(allow_prompt=False, required=False)
            if config:
                print(f"✓ Ready to use UUID: {config.uuid}")
            else:
                print("⚠ No UUID configured. Run: python -m src --setup-config")
        finally:
            fetcher.close()
            
    except Exception as e:
        print(f"✗ Error: {e}")


def example_5_multiple_sources():
    """Example 5: UUID loading priority."""
    print("\n" + "=" * 60)
    print("Example 5: UUID Loading Priority")
    print("=" * 60)
    
    print("""
UUID is loaded from sources in this priority order:

1. Environment Variable (EMSX_UUID or BLOOMBERG_UUID)
   → Highest priority, useful for CI/CD
   
2. External Provider (keyring, vault, etc.)
   → Set via set_external_provider()
   
3. Secure Credentials File (~/.config/fillfetch/credentials.json)
   → Created by --setup-config, permission 0o600
   
4. Interactive Prompt
   → Only if allow_prompt=True

The first valid UUID found is used and cached.
""")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("FillFetch Secure UUID Management Examples")
    print("=" * 60)
    
    examples = [
        example_1_basic_usage,
        example_2_explicit_override,
        example_3_validation,
        example_4_fetch_integration,
        example_5_multiple_sources,
    ]
    
    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"\nError in {example.__name__}: {e}")
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)
    print("""
Next steps:
  1. Configure UUID:   python -m src --setup-config
  2. Validate config:  python -m src --validate-config
  3. Fetch fills:      python -m src --date 2024-01-15
""")


if __name__ == '__main__':
    main()
