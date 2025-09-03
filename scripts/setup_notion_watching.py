#!/usr/bin/env python3
"""
Setup script for enabling Notion integration with the watching system.

This script helps configure Notion credentials and enable the integration
for automatic sync during file watching.
"""

import os
import sys
from pathlib import Path
import getpass

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import Config

def main():
    print("🔗 Notion Integration Setup for Watching System")
    print("=" * 60)
    print()
    
    # Load config
    config = Config()
    
    # Get Notion credentials
    print("📝 Please provide your Notion integration credentials:")
    print("💡 Get these from: https://developers.notion.com/")
    print()
    
    # Check if already configured
    existing_token = os.getenv('NOTION_TOKEN') or config.get('integrations.notion.api_token')
    existing_db_id = os.getenv('NOTION_DATABASE_ID') or config.get('integrations.notion.database_id')
    
    if existing_token and existing_db_id:
        print("✅ Notion credentials already configured!")
        print(f"   Token: {existing_token[:20]}...")
        print(f"   Database: {existing_db_id}")
        print()
        
        if input("Continue with existing credentials? (y/N): ").lower().strip() == 'y':
            token = existing_token
            database_id = existing_db_id
        else:
            token = None
            database_id = None
    else:
        token = None
        database_id = None
    
    # Get token if needed
    if not token:
        try:
            token = getpass.getpass("Enter your Notion integration token (starts with 'secret_'): ").strip()
            if not token.startswith('secret_'):
                print("⚠️  Warning: Notion tokens usually start with 'secret_'")
                if input("Continue anyway? (y/N): ").lower().strip() != 'y':
                    print("❌ Setup cancelled")
                    return False
        except KeyboardInterrupt:
            print("\n❌ Setup cancelled")
            return False
    
    # Get database ID if needed
    if not database_id:
        print("\n📊 Database ID:")
        print("💡 Copy from your Notion database URL: https://notion.so/workspace/DATABASE_ID?v=...")
        print("   (The 32-character ID between the last '/' and '?')")
        print()
        
        database_id = input("Enter your Notion database ID (32 characters): ").strip()
        
        if len(database_id) != 32:
            print("⚠️  Warning: Database IDs are usually 32 characters long")
            if input("Continue anyway? (y/N): ").lower().strip() != 'y':
                print("❌ Setup cancelled")
                return False
    
    print("\n🧪 Testing Notion connection...")
    
    try:
        # Test the connection
        from src.integrations.notion_sync import NotionNotebookSync
        test_client = NotionNotebookSync(token, database_id, verify_ssl=False)
        
        # Try to access the database
        from notion_client.errors import APIResponseError
        try:
            response = test_client.client.databases.query(database_id=database_id, page_size=1)
            print("✅ Connection successful!")
        except APIResponseError as e:
            if "not found" in str(e).lower():
                print("❌ Database not found or not shared with integration")
                print("💡 Make sure to:")
                print("   1. Share your database with the integration")
                print("   2. Use the correct database ID")
                return False
            else:
                raise
        
    except ImportError:
        print("❌ notion-client not installed. Run: poetry add notion-client")
        return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False
    
    print("\n💾 Saving configuration...")
    
    # Update config file
    config.set('integrations.notion.enabled', True)
    config.set('integrations.notion.api_token', token)
    config.set('integrations.notion.database_id', database_id)
    
    # Save config
    config_path = project_root / 'config' / 'config.yaml'
    config.save(config_path)
    
    print("✅ Configuration saved to config.yaml")
    print()
    
    # Also provide environment variable option
    print("🌍 Alternative: You can also use environment variables:")
    print(f"   export NOTION_TOKEN=\"{token}\"")
    print(f"   export NOTION_DATABASE_ID=\"{database_id}\"")
    print()
    
    print("🚀 Setup complete! You can now run the watching system with Notion integration:")
    print("   poetry run python src/cli/main.py watch")
    print()
    print("💡 The system will automatically:")
    print("   • Watch for reMarkable changes")
    print("   • Process new/modified notebooks")
    print("   • Sync changes to Notion with markdown formatting")
    print("   • Only update notebooks that have actually changed")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n❌ Setup cancelled")
        sys.exit(1)