#!/usr/bin/env python3
"""
Secrets management utility for reMarkable Integration.

Provides a command-line interface for securely managing API tokens
and other sensitive configuration values.
"""

import sys
import getpass
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.secrets import secrets_manager, get_secret, set_secret
from src.utils.config import Config


def list_secrets():
    """List all configured secrets (without revealing values)."""
    print("🔐 Configured Secrets Status")
    print("=" * 40)
    
    stored_secrets = secrets_manager.list_stored_secrets()
    
    for key, exists in stored_secrets.items():
        status = "✅ Configured" if exists else "❌ Missing"
        print(f"  {key}: {status}")
        
        if exists:
            # Show where it's coming from
            value = get_secret(key)
            if value:
                masked = f"{'*' * (len(value) - 4)}{value[-4:]}" if len(value) > 4 else "***"
                print(f"    Value: {masked}")
    
    print(f"\nKeyring backend: {secrets_manager.get_keyring_backend()}")
    print(f"Keyring available: {'✅ Yes' if secrets_manager._keyring_available else '❌ No'}")


def set_readwise_token():
    """Interactively set the Readwise API token."""
    print("🔗 Setting up Readwise Integration")
    print("=" * 35)
    
    print("\n1. Get your Readwise access token:")
    print("   👉 Visit: https://readwise.io/access_token")
    print("   👉 Copy your access token")
    
    print("\n2. Enter your token below:")
    token = getpass.getpass("Readwise API Token: ").strip()
    
    if not token:
        print("❌ No token provided")
        return False
    
    # Store the token
    if secrets_manager._keyring_available:
        success = set_secret("readwise.api_token", token)
        if success:
            print("✅ Readwise token stored securely in system keyring")
        else:
            print("❌ Failed to store in keyring")
            return False
    else:
        env_cmd = secrets_manager.export_to_env("readwise.api_token")
        print("⚠️  System keyring not available")
        print("Set environment variable instead:")
        print(f"   {env_cmd.replace('your_token_here', token)}")
        return False
    
    # Update config to enable Readwise
    try:
        config = Config()
        config.set("integrations.readwise.enabled", True)
        config.save()
        print("✅ Readwise integration enabled in configuration")
    except Exception as e:
        print(f"⚠️  Warning: Could not update config file: {e}")
    
    # Test the token
    print("\n🧪 Testing token...")
    from src.integrations.readwise_sync import ReadwiseAPIClient
    import asyncio
    
    async def test_token():
        async with ReadwiseAPIClient(token) as client:
            return await client.test_connection()
    
    try:
        if asyncio.run(test_token()):
            print("✅ Readwise API connection successful!")
            return True
        else:
            print("❌ Readwise API connection failed - check your token")
            return False
    except Exception as e:
        print(f"❌ Error testing Readwise connection: {e}")
        return False


def set_notion_token():
    """Interactively set the Notion API token."""
    print("📝 Setting up Notion Integration")
    print("=" * 32)
    
    print("\n1. Get your Notion integration token:")
    print("   👉 Visit: https://developers.notion.com/")
    print("   👉 Create an integration and copy the token")
    
    print("\n2. Enter your token below:")
    token = getpass.getpass("Notion API Token: ").strip()
    
    if not token:
        print("❌ No token provided")
        return False
    
    # Store the token
    if secrets_manager._keyring_available:
        success = set_secret("notion.api_token", token)
        if success:
            print("✅ Notion token stored securely in system keyring")
            return True
        else:
            print("❌ Failed to store in keyring")
            return False
    else:
        env_cmd = secrets_manager.export_to_env("notion.api_token")
        print("⚠️  System keyring not available")
        print("Set environment variable instead:")
        print(f"   {env_cmd.replace('your_token_here', token)}")
        return False


def show_usage():
    """Show usage information."""
    print("🔧 Secrets Management Utility")
    print("=" * 32)
    print("\nUsage:")
    print("  python manage_secrets.py <command>")
    print("\nCommands:")
    print("  list                 - List all configured secrets")
    print("  set-readwise         - Set up Readwise API token")  
    print("  set-notion           - Set up Notion API token")
    print("  show-env-vars        - Show environment variable commands")
    print("  test-config          - Test current configuration")
    print("\nFor more secure storage, this tool uses your system keyring.")
    print("Fallback: set environment variables if keyring unavailable.")


def show_env_vars():
    """Show environment variable commands for all secrets."""
    print("🌍 Environment Variable Setup")
    print("=" * 32)
    print("\nIf system keyring is not available, use these commands:")
    print()
    
    secrets_info = [
        ("Readwise API Token", "readwise.api_token", "https://readwise.io/access_token"),
        ("Notion API Token", "notion.api_token", "https://developers.notion.com/"),
        ("Notion Database ID", "notion.database_id", "Copy from your Notion database URL"),
    ]
    
    for name, key, source in secrets_info:
        print(f"# {name}")
        print(f"# Get from: {source}")
        print(f"{secrets_manager.export_to_env(key)}")
        print()


def test_config():
    """Test the current configuration including secrets."""
    print("🧪 Testing Configuration")
    print("=" * 25)
    
    try:
        config = Config()
        
        print("\n📋 Configuration file:")
        print(f"  Path: {config.config_path}")
        
        print("\n🔐 Secrets status:")
        stored_secrets = secrets_manager.list_stored_secrets()
        for key, exists in stored_secrets.items():
            status = "✅" if exists else "❌"
            print(f"  {status} {key}")
        
        print("\n⚙️  Integration status:")
        
        # Check Readwise
        readwise_enabled = config.get("integrations.readwise.enabled", False)
        readwise_token = config.get_secret_aware("integrations.readwise.api_token")
        print(f"  Readwise: {'✅ Enabled' if readwise_enabled and readwise_token else '❌ Disabled or missing token'}")
        
        # Check Notion  
        notion_enabled = config.get("integrations.notion.enabled", False)
        notion_token = config.get_secret_aware("integrations.notion.api_token")
        print(f"  Notion: {'✅ Enabled' if notion_enabled and notion_token else '❌ Disabled or missing token'}")
        
        print("\n✅ Configuration test completed")
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False
    
    return True


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_usage()
        return
    
    command = sys.argv[1].lower()
    
    if command == "list":
        list_secrets()
    elif command == "set-readwise":
        set_readwise_token()
    elif command == "set-notion":
        set_notion_token()
    elif command == "show-env-vars":
        show_env_vars()
    elif command == "test-config":
        test_config()
    else:
        print(f"❌ Unknown command: {command}")
        print()
        show_usage()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user")
    except Exception as e:
        print(f"\n💥 Error: {e}")
        sys.exit(1)