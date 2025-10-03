"""
Secure secrets management for reMarkable Integration.

Provides secure storage and retrieval of sensitive configuration like API tokens
using the system keyring with fallback to environment variables.
"""

import keyring
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Application identifier for keyring
APP_NAME = "remarkable-integration"


class SecretsManager:
    """
    Secure secrets management using system keyring.
    
    Stores sensitive configuration like API tokens in the system keyring
    rather than in plain text configuration files.
    """
    
    def __init__(self, app_name: str = APP_NAME):
        self.app_name = app_name
        self.logger = logging.getLogger(f"{__name__}.SecretsManager")
        
        # Test keyring availability
        self._keyring_available = self._test_keyring()
    
    def _test_keyring(self) -> bool:
        """Test if keyring is available and working."""
        try:
            # Try a test operation
            test_key = f"{self.app_name}.test"
            keyring.set_password(self.app_name, test_key, "test")
            retrieved = keyring.get_password(self.app_name, test_key)
            keyring.delete_password(self.app_name, test_key)
            
            if retrieved == "test":
                self.logger.info("System keyring is available and working")
                return True
            else:
                self.logger.warning("System keyring test failed - using fallback")
                return False
                
        except Exception as e:
            self.logger.warning(f"System keyring not available: {e} - using fallback")
            return False
    
    def get_secret(self, key: str) -> Optional[str]:
        """
        Get a secret value.
        
        Tries in order:
        1. System keyring
        2. Environment variable
        3. Returns None
        
        Args:
            key: Secret key name
            
        Returns:
            Secret value or None if not found
        """
        # Try keyring first
        if self._keyring_available:
            try:
                value = keyring.get_password(self.app_name, key)
                if value:
                    self.logger.debug(f"Retrieved secret '{key}' from keyring")
                    return value
            except Exception as e:
                self.logger.warning(f"Error retrieving secret from keyring: {e}")
        
        # Fallback to environment variable
        env_key = self._key_to_env_var(key)
        value = os.getenv(env_key)
        if value:
            self.logger.debug(f"Retrieved secret '{key}' from environment variable '{env_key}'")
            return value
        
        self.logger.debug(f"Secret '{key}' not found")
        return None
    
    def set_secret(self, key: str, value: str) -> bool:
        """
        Set a secret value in the keyring.
        
        Args:
            key: Secret key name
            value: Secret value
            
        Returns:
            True if successful, False otherwise
        """
        if not self._keyring_available:
            self.logger.warning(f"Cannot set secret '{key}' - keyring not available")
            return False
        
        try:
            keyring.set_password(self.app_name, key, value)
            self.logger.info(f"Secret '{key}' stored in keyring")
            return True
        except Exception as e:
            self.logger.error(f"Error storing secret in keyring: {e}")
            return False
    
    def delete_secret(self, key: str) -> bool:
        """
        Delete a secret from the keyring.
        
        Args:
            key: Secret key name
            
        Returns:
            True if successful, False otherwise
        """
        if not self._keyring_available:
            return False
        
        try:
            keyring.delete_password(self.app_name, key)
            self.logger.info(f"Secret '{key}' deleted from keyring")
            return True
        except Exception as e:
            self.logger.warning(f"Error deleting secret from keyring: {e}")
            return False
    
    def list_stored_secrets(self) -> Dict[str, bool]:
        """
        Get a list of stored secrets (keys only, not values).
        
        Returns:
            Dictionary mapping secret keys to whether they exist
        """
        common_secrets = [
            "readwise.api_token",
            "notion.api_token", 
            "notion.database_id",
            "microsoft_todo.client_id",
            "microsoft_todo.client_secret",
        ]
        
        result = {}
        for key in common_secrets:
            result[key] = bool(self.get_secret(key))
        
        return result
    
    def _key_to_env_var(self, key: str) -> str:
        """
        Convert a secret key to environment variable name.
        
        Args:
            key: Secret key (e.g., 'readwise.api_token')
            
        Returns:
            Environment variable name (e.g., 'READWISE_API_TOKEN')
        """
        # Convert dots to underscores and uppercase
        env_var = key.replace('.', '_').upper()
        
        # Add prefix for standard environment variables
        mapping = {
            'READWISE_API_TOKEN': 'READWISE_API_TOKEN',
            'NOTION_API_TOKEN': 'NOTION_API_TOKEN',
            'NOTION_DATABASE_ID': 'NOTION_DATABASE_ID',
            'MICROSOFT_TODO_CLIENT_ID': 'MICROSOFT_TODO_CLIENT_ID',
            'MICROSOFT_TODO_CLIENT_SECRET': 'MICROSOFT_TODO_CLIENT_SECRET',
        }
        
        return mapping.get(env_var, env_var)
    
    def export_to_env(self, key: str) -> str:
        """
        Get export command for environment variable.
        
        Args:
            key: Secret key name
            
        Returns:
            Export command string
        """
        env_var = self._key_to_env_var(key)
        return f"export {env_var}='your_token_here'"
    
    def get_keyring_backend(self) -> str:
        """Get information about the keyring backend being used."""
        try:
            backend = keyring.get_keyring()
            return f"{backend.__class__.__module__}.{backend.__class__.__name__}"
        except Exception:
            return "Unknown or unavailable"


# Global secrets manager instance
secrets_manager = SecretsManager()


def get_secret(key: str) -> Optional[str]:
    """Convenience function to get a secret."""
    return secrets_manager.get_secret(key)


def set_secret(key: str, value: str) -> bool:
    """Convenience function to set a secret."""
    return secrets_manager.set_secret(key, value)


if __name__ == "__main__":
    # Example usage and testing
    import sys
    
    def test_secrets_manager():
        """Test the secrets manager functionality."""
        print("🔐 Testing Secrets Manager")
        print("=" * 30)
        
        # Test keyring availability
        print(f"Keyring available: {secrets_manager._keyring_available}")
        print(f"Keyring backend: {secrets_manager.get_keyring_backend()}")
        
        # Test getting existing secrets
        print("\n📋 Current secrets status:")
        stored_secrets = secrets_manager.list_stored_secrets()
        for key, exists in stored_secrets.items():
            status = "✅ Found" if exists else "❌ Missing"
            print(f"  {key}: {status}")
        
        # Show how to set secrets
        print("\n🔧 How to set secrets:")
        for key in ["readwise.api_token", "notion.api_token"]:
            print(f"  {secrets_manager.export_to_env(key)}")
        
        # Test retrieval
        print("\n🔍 Testing secret retrieval:")
        readwise_token = get_secret("readwise.api_token")
        if readwise_token:
            print(f"  Readwise token: {'*' * (len(readwise_token) - 4)}{readwise_token[-4:]}")
        else:
            print("  Readwise token: Not configured")
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_secrets_manager()
    else:
        print("Usage: python secrets.py test")
        print("Or import and use get_secret() and set_secret() functions")