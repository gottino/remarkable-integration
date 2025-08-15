"""
Secure API Key Management for reMarkable Integration.

Provides multiple secure methods for storing and retrieving API keys:
1. Configuration file (encrypted)
2. Environment variables
3. Keychain/Credential store (OS-specific)
4. Interactive prompt with secure input
"""

import os
import sys
import logging
import getpass
from typing import Optional, Dict, Any
from pathlib import Path
import json

# Try to import keyring for secure storage
try:
    import keyring
    import keyring.errors
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

# Try to import cryptography for encrypted storage
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

logger = logging.getLogger(__name__)


class APIKeyManager:
    """Secure API key management with multiple storage backends."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize API key manager.
        
        Args:
            config_dir: Directory for configuration files (default: ~/.remarkable-integration)
        """
        self.config_dir = config_dir or Path.home() / '.remarkable-integration'
        self.config_dir.mkdir(exist_ok=True, mode=0o700)  # Secure permissions
        
        self.keyfile_path = self.config_dir / 'api_keys.json'
        self.service_name = 'remarkable-integration'
        
        logger.debug(f"API Key Manager initialized with config dir: {self.config_dir}")
    
    def get_anthropic_api_key(self) -> Optional[str]:
        """
        Get Anthropic API key from various sources in order of preference:
        1. Environment variable ANTHROPIC_API_KEY
        2. Keychain/Credential store
        3. Encrypted configuration file
        4. Interactive prompt (if terminal available)
        
        Returns:
            API key string or None if not found/configured
        """
        # 1. Check environment variable first
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if api_key:
            logger.debug("API key found in environment variable")
            return api_key
        
        # 2. Check system keychain/credential store
        api_key = self._get_from_keychain('anthropic')
        if api_key:
            logger.debug("API key found in system keychain")
            return api_key
        
        # 3. Check encrypted configuration file
        api_key = self._get_from_encrypted_config('anthropic')
        if api_key:
            logger.debug("API key found in encrypted configuration")
            return api_key
        
        # 4. Interactive prompt if terminal available
        if sys.stdin.isatty():
            logger.info("No API key found. Starting interactive setup...")
            api_key = self._prompt_for_api_key('anthropic')
            if api_key:
                # Store for future use
                self.store_anthropic_api_key(api_key)
                return api_key
        
        logger.warning("No Anthropic API key found. Use 'config api-key set' command to configure.")
        return None
    
    def store_anthropic_api_key(self, api_key: str, method: str = 'auto') -> bool:
        """
        Store Anthropic API key securely.
        
        Args:
            api_key: The API key to store
            method: Storage method ('keychain', 'encrypted', 'auto')
            
        Returns:
            True if stored successfully, False otherwise
        """
        if method == 'auto':
            # Try keychain first, fallback to encrypted file
            if self._store_in_keychain('anthropic', api_key):
                logger.info("API key stored in system keychain")
                return True
            elif self._store_in_encrypted_config('anthropic', api_key):
                logger.info("API key stored in encrypted configuration file")
                return True
            else:
                logger.error("Failed to store API key securely")
                return False
        
        elif method == 'keychain':
            return self._store_in_keychain('anthropic', api_key)
        
        elif method == 'encrypted':
            return self._store_in_encrypted_config('anthropic', api_key)
        
        else:
            logger.error(f"Unknown storage method: {method}")
            return False
    
    def remove_anthropic_api_key(self) -> bool:
        """Remove stored Anthropic API key from all locations."""
        removed = False
        
        # Remove from keychain
        if self._remove_from_keychain('anthropic'):
            logger.info("API key removed from keychain")
            removed = True
        
        # Remove from encrypted config
        if self._remove_from_encrypted_config('anthropic'):
            logger.info("API key removed from encrypted configuration")
            removed = True
        
        return removed
    
    def list_stored_keys(self) -> Dict[str, str]:
        """List all stored API keys and their storage locations."""
        keys = {}
        
        # Check environment
        if os.getenv('ANTHROPIC_API_KEY'):
            keys['anthropic'] = 'environment'
        
        # Check keychain
        if self._get_from_keychain('anthropic'):
            keys['anthropic'] = 'keychain'
        
        # Check encrypted config
        elif self._get_from_encrypted_config('anthropic'):
            keys['anthropic'] = 'encrypted_file'
        
        return keys
    
    def _get_from_keychain(self, service: str) -> Optional[str]:
        """Get API key from system keychain."""
        if not KEYRING_AVAILABLE:
            return None
        
        try:
            username = f"{service}_api_key"
            api_key = keyring.get_password(self.service_name, username)
            return api_key
        except keyring.errors.KeyringError as e:
            logger.debug(f"Keychain access failed: {e}")
            return None
        except Exception as e:
            logger.debug(f"Unexpected keychain error: {e}")
            return None
    
    def _store_in_keychain(self, service: str, api_key: str) -> bool:
        """Store API key in system keychain."""
        if not KEYRING_AVAILABLE:
            logger.debug("Keyring not available")
            return False
        
        try:
            username = f"{service}_api_key"
            keyring.set_password(self.service_name, username, api_key)
            
            # Verify storage
            stored_key = keyring.get_password(self.service_name, username)
            return stored_key == api_key
            
        except keyring.errors.KeyringError as e:
            logger.debug(f"Failed to store in keychain: {e}")
            return False
        except Exception as e:
            logger.debug(f"Unexpected keychain error: {e}")
            return False
    
    def _remove_from_keychain(self, service: str) -> bool:
        """Remove API key from system keychain."""
        if not KEYRING_AVAILABLE:
            return False
        
        try:
            username = f"{service}_api_key"
            keyring.delete_password(self.service_name, username)
            return True
        except keyring.errors.PasswordDeleteError:
            # Key not found
            return False
        except keyring.errors.KeyringError as e:
            logger.debug(f"Failed to remove from keychain: {e}")
            return False
        except Exception as e:
            logger.debug(f"Unexpected keychain error: {e}")
            return False
    
    def _get_from_encrypted_config(self, service: str) -> Optional[str]:
        """Get API key from encrypted configuration file."""
        if not ENCRYPTION_AVAILABLE or not self.keyfile_path.exists():
            return None
        
        try:
            # Read encrypted data
            with open(self.keyfile_path, 'rb') as f:
                encrypted_data = f.read()
            
            # Decrypt using machine-specific key
            fernet = self._get_fernet()
            decrypted_data = fernet.decrypt(encrypted_data)
            
            # Parse JSON
            config = json.loads(decrypted_data.decode('utf-8'))
            return config.get(f"{service}_api_key")
            
        except Exception as e:
            logger.debug(f"Failed to read encrypted config: {e}")
            return None
    
    def _store_in_encrypted_config(self, service: str, api_key: str) -> bool:
        """Store API key in encrypted configuration file."""
        if not ENCRYPTION_AVAILABLE:
            logger.debug("Encryption not available")
            return False
        
        try:
            # Load existing config or create new
            config = {}
            if self.keyfile_path.exists():
                existing_key = self._get_from_encrypted_config(service)
                if existing_key:
                    # Load full config to preserve other keys
                    with open(self.keyfile_path, 'rb') as f:
                        encrypted_data = f.read()
                    fernet = self._get_fernet()
                    decrypted_data = fernet.decrypt(encrypted_data)
                    config = json.loads(decrypted_data.decode('utf-8'))
            
            # Update with new key
            config[f"{service}_api_key"] = api_key
            
            # Encrypt and save
            fernet = self._get_fernet()
            data_to_encrypt = json.dumps(config).encode('utf-8')
            encrypted_data = fernet.encrypt(data_to_encrypt)
            
            # Write with secure permissions
            self.keyfile_path.write_bytes(encrypted_data)
            self.keyfile_path.chmod(0o600)  # Read/write for owner only
            
            return True
            
        except Exception as e:
            logger.debug(f"Failed to store in encrypted config: {e}")
            return False
    
    def _remove_from_encrypted_config(self, service: str) -> bool:
        """Remove API key from encrypted configuration file."""
        if not ENCRYPTION_AVAILABLE or not self.keyfile_path.exists():
            return False
        
        try:
            # Load existing config
            with open(self.keyfile_path, 'rb') as f:
                encrypted_data = f.read()
            fernet = self._get_fernet()
            decrypted_data = fernet.decrypt(encrypted_data)
            config = json.loads(decrypted_data.decode('utf-8'))
            
            # Remove key if exists
            key_name = f"{service}_api_key"
            if key_name in config:
                del config[key_name]
                
                # If config is empty, remove file
                if not config:
                    self.keyfile_path.unlink()
                    return True
                
                # Otherwise, save updated config
                data_to_encrypt = json.dumps(config).encode('utf-8')
                encrypted_data = fernet.encrypt(data_to_encrypt)
                self.keyfile_path.write_bytes(encrypted_data)
                self.keyfile_path.chmod(0o600)
                
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Failed to remove from encrypted config: {e}")
            return False
    
    def _get_fernet(self) -> 'Fernet':
        """Get Fernet encryption instance with machine-specific key."""
        # Use machine-specific data to derive encryption key
        machine_data = f"{os.uname().nodename}-{os.uname().machine}-{self.service_name}".encode()
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'remarkable-integration-salt',  # Fixed salt for consistency
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_data))
        return Fernet(key)
    
    def _prompt_for_api_key(self, service: str) -> Optional[str]:
        """Prompt user for API key with secure input."""
        try:
            print(f"\n🔑 {service.title()} API Key Setup")
            print("=" * 40)
            print(f"To use AI-powered OCR, you need a {service.title()} API key.")
            print(f"Get your API key from: https://console.anthropic.com/")
            print("")
            
            api_key = getpass.getpass("Enter your API key (input hidden): ").strip()
            
            if not api_key:
                print("No API key entered.")
                return None
            
            # Basic validation
            if service == 'anthropic' and not api_key.startswith('sk-ant-'):
                print("⚠️  Warning: Anthropic API keys usually start with 'sk-ant-'")
                confirm = input("Continue anyway? (y/N): ").strip().lower()
                if confirm != 'y':
                    return None
            
            # Confirm storage method
            storage_options = []
            if KEYRING_AVAILABLE:
                storage_options.append("keychain")
            if ENCRYPTION_AVAILABLE:
                storage_options.append("encrypted file")
            
            if storage_options:
                print(f"\nAvailable storage options: {', '.join(storage_options)}")
                print("The API key will be stored securely for future use.")
            
            return api_key
            
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            return None
        except Exception as e:
            logger.error(f"Error during interactive setup: {e}")
            return None


# Global instance
_api_key_manager = None


def get_api_key_manager() -> APIKeyManager:
    """Get global API key manager instance."""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager


def get_anthropic_api_key() -> Optional[str]:
    """Convenience function to get Anthropic API key."""
    return get_api_key_manager().get_anthropic_api_key()


# Test function
if __name__ == "__main__":
    import sys
    
    manager = APIKeyManager()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "get":
            api_key = manager.get_anthropic_api_key()
            if api_key:
                print(f"API key found: {api_key[:12]}...")
            else:
                print("No API key found")
        
        elif command == "set":
            if len(sys.argv) > 2:
                api_key = sys.argv[2]
                if manager.store_anthropic_api_key(api_key):
                    print("API key stored successfully")
                else:
                    print("Failed to store API key")
            else:
                print("Usage: python api_keys.py set <api_key>")
        
        elif command == "remove":
            if manager.remove_anthropic_api_key():
                print("API key removed")
            else:
                print("No API key to remove")
        
        elif command == "list":
            keys = manager.list_stored_keys()
            if keys:
                print("Stored API keys:")
                for service, location in keys.items():
                    print(f"  {service}: {location}")
            else:
                print("No API keys stored")
        
        else:
            print("Usage: python api_keys.py [get|set <key>|remove|list]")
    
    else:
        print("Testing API key management...")
        keys = manager.list_stored_keys()
        print(f"Available keys: {keys}")
        
        api_key = manager.get_anthropic_api_key()
        if api_key:
            print(f"API key available: {api_key[:12]}...")
        else:
            print("No API key configured")