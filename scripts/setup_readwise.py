#!/usr/bin/env python3
"""
Setup script for Readwise integration.

This script helps you securely configure your Readwise API token
using the existing API key management system.
"""

import sys
import getpass
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.api_keys import get_api_key_manager, get_readwise_api_key
from src.utils.config import Config


def setup_readwise():
    """Interactive setup for Readwise integration."""
    print("🔗 Readwise Integration Setup")
    print("=" * 35)
    
    # Check if already configured
    existing_key = get_readwise_api_key()
    if existing_key:
        masked_key = f"{'*' * (len(existing_key) - 4)}{existing_key[-4:]}" if len(existing_key) > 4 else "***"
        print(f"✅ Readwise API key already configured: {masked_key}")
        
        overwrite = input("Do you want to update it? (y/N): ").strip().lower()
        if overwrite != 'y':
            print("Setup cancelled.")
            return True
    
    print("\n📝 Step 1: Get your Readwise access token")
    print("   👉 Visit: https://readwise.io/access_token")
    print("   👉 Copy your access token")
    print("   👉 The token is usually a long string of random characters")
    
    print("\n🔑 Step 2: Enter your token")
    token = getpass.getpass("Readwise API Token (input hidden): ").strip()
    
    if not token:
        print("❌ No token provided. Setup cancelled.")
        return False
    
    # Basic validation - just check it's not too short
    if len(token) < 10:
        print("⚠️  Warning: This token seems very short")
        confirm = input("Continue anyway? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Setup cancelled.")
            return False
    
    # Store the token using the secure API key manager
    manager = get_api_key_manager()
    
    print("\n💾 Step 3: Storing token securely...")
    success = manager.store_readwise_api_key(token)
    
    if success:
        print("✅ Readwise token stored securely!")
        
        # Show where it was stored
        keys = manager.list_stored_keys()
        if 'readwise' in keys:
            location = keys['readwise']
            if location == 'keychain':
                print("   📱 Stored in system keychain (most secure)")
            elif location == 'encrypted_file':
                print("   🔒 Stored in encrypted file")
            else:
                print(f"   📁 Stored in {location}")
    else:
        print("❌ Failed to store token securely.")
        print("   💡 You can set it as an environment variable instead:")
        print("   export READWISE_API_TOKEN='your_token_here'")
        return False
    
    # Update configuration to enable Readwise
    print("\n⚙️  Step 4: Enabling Readwise integration...")
    try:
        config = Config()
        config.set("integrations.readwise.enabled", True)
        config.save()
        print("✅ Readwise integration enabled in configuration")
    except Exception as e:
        print(f"⚠️  Warning: Could not update config file: {e}")
        print("   💡 You can manually set 'integrations.readwise.enabled: true' in your config.yaml")
    
    # Test the connection
    print("\n🧪 Step 5: Testing connection...")
    try:
        from src.integrations.readwise_sync import ReadwiseAPIClient
        import asyncio
        
        async def test_connection():
            async with ReadwiseAPIClient(token) as client:
                return await client.test_connection()
        
        if asyncio.run(test_connection()):
            print("✅ Readwise API connection successful!")
            print("\n🎉 Setup Complete!")
            print("=" * 20)
            print("Your Readwise integration is now ready to use.")
            print("The system will automatically sync:")
            print("  • 📖 Notebook pages as highlights")
            print("  • 💡 Individual highlights with OCR corrections")  
            print("  • 📝 Todo items as tasks")
            return True
        else:
            print("❌ Readwise API connection failed")
            print("   💡 Please check your token and try again")
            return False
            
    except Exception as e:
        print(f"❌ Error testing connection: {e}")
        print("   💡 The token is stored, but connection test failed")
        return False


def show_status():
    """Show current Readwise configuration status."""
    print("📊 Readwise Integration Status")
    print("=" * 32)
    
    # Check API key
    api_key = get_readwise_api_key()
    if api_key:
        masked_key = f"{'*' * (len(api_key) - 4)}{api_key[-4:]}" if len(api_key) > 4 else "***"
        print(f"🔑 API Key: ✅ Configured ({masked_key})")
        
        # Check where it's stored
        manager = get_api_key_manager()
        keys = manager.list_stored_keys()
        if 'readwise' in keys:
            location = keys['readwise']
            print(f"📍 Storage: {location}")
    else:
        print("🔑 API Key: ❌ Not configured")
    
    # Check configuration
    try:
        config = Config()
        enabled = config.get("integrations.readwise.enabled", False)
        print(f"⚙️  Integration: {'✅ Enabled' if enabled else '❌ Disabled'}")
    except Exception as e:
        print(f"⚙️  Integration: ❌ Config error: {e}")


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "setup":
            setup_readwise()
        elif command == "status":
            show_status()
        else:
            print(f"Unknown command: {command}")
            print("Usage: python setup_readwise.py [setup|status]")
    else:
        # Default to setup
        setup_readwise()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Setup interrupted")
    except Exception as e:
        print(f"\n💥 Error: {e}")
        sys.exit(1)