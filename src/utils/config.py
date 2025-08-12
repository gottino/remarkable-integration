"""
Configuration management for reMarkable Integration.

Handles loading and managing configuration from YAML files and environment variables.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


class Config:
    """Configuration manager for the reMarkable integration."""
    
    DEFAULT_CONFIG = {
        'remarkable': {
            'sync_directory': None,
            'backup_directory': None,
        },
        'database': {
            'path': 'remarkable_pipeline.db',
            'backup_enabled': True,
            'backup_interval_hours': 24,
        },
        'processing': {
            'highlight_extraction': {
                'enabled': True,
                'min_text_length': 8,
                'text_threshold': 0.4,
                'min_words': 2,
                'symbol_ratio_threshold': 0.3,
            },
            'ocr': {
                'enabled': False,
                'language': 'en',
                'confidence_threshold': 0.7,
            },
            'file_watching': {
                'enabled': True,
                'watch_patterns': ['*.content', '*.rm'],
                'ignore_patterns': ['.*', '*.tmp'],
            },
        },
        'integrations': {
            'notion': {
                'enabled': False,
                'api_token': None,
                'database_id': None,
            },
            'readwise': {
                'enabled': False,
                'api_token': None,
            },
            'microsoft_todo': {
                'enabled': False,
                'client_id': None,
                'client_secret': None,
            },
        },
        'logging': {
            'level': 'INFO',
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            'file': None,  # None means console only
        },
    }
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to configuration file. If None, looks for config in standard locations.
        """
        self.config_data = self.DEFAULT_CONFIG.copy()
        self.config_path = self._find_config_file(config_path)
        
        if self.config_path:
            self._load_config_file()
        else:
            logger.info("No configuration file found, using defaults")
        
        # Override with environment variables
        self._load_env_variables()
        
        logger.debug(f"Configuration loaded from {self.config_path or 'defaults'}")
    
    def _find_config_file(self, config_path: Optional[str]) -> Optional[Path]:
        """Find the configuration file to use."""
        if config_path:
            path = Path(config_path)
            if path.exists():
                return path
            else:
                logger.warning(f"Specified config file not found: {config_path}")
                return None
        
        # Look for config in standard locations
        search_paths = [
            Path.cwd() / 'config.yaml',
            Path.cwd() / 'config' / 'config.yaml',
            Path.home() / '.remarkable-integration' / 'config.yaml',
            Path.home() / '.config' / 'remarkable-integration' / 'config.yaml',
        ]
        
        for path in search_paths:
            if path.exists():
                logger.info(f"Found configuration file: {path}")
                return path
        
        return None
    
    def _load_config_file(self):
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, 'r') as f:
                file_config = yaml.safe_load(f) or {}
            
            # Merge with defaults (deep merge)
            self.config_data = self._deep_merge(self.config_data, file_config)
            logger.info(f"Configuration loaded from {self.config_path}")
            
        except Exception as e:
            logger.error(f"Error loading config file {self.config_path}: {e}")
            logger.info("Using default configuration")
    
    def _load_env_variables(self):
        """Load configuration from environment variables."""
        env_mappings = {
            'REMARKABLE_SYNC_DIR': ['remarkable', 'sync_directory'],
            'REMARKABLE_DB_PATH': ['database', 'path'],
            'REMARKABLE_LOG_LEVEL': ['logging', 'level'],
            'REMARKABLE_LOG_FILE': ['logging', 'file'],
            'NOTION_API_TOKEN': ['integrations', 'notion', 'api_token'],
            'NOTION_DATABASE_ID': ['integrations', 'notion', 'database_id'],
            'READWISE_API_TOKEN': ['integrations', 'readwise', 'api_token'],
        }
        
        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value:
                self._set_nested_value(self.config_data, config_path, value)
                logger.debug(f"Set config from env var {env_var}")
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _set_nested_value(self, data: Dict, path: list, value: Any):
        """Set a nested value in a dictionary using a path list."""
        current = data
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        # Convert string values to appropriate types
        if isinstance(value, str):
            if value.lower() in ('true', 'false'):
                value = value.lower() == 'true'
            elif value.isdigit():
                value = int(value)
            elif value.replace('.', '').isdigit():
                value = float(value)
        
        current[path[-1]] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key: Configuration key in dot notation (e.g., 'database.path')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        current = self.config_data
        
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        
        return current
    
    def set(self, key: str, value: Any):
        """
        Set configuration value using dot notation.
        
        Args:
            key: Configuration key in dot notation
            value: Value to set
        """
        keys = key.split('.')
        self._set_nested_value(self.config_data, keys, value)
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section."""
        return self.get(section, {})
    
    def is_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled."""
        return bool(self.get(f'{feature}.enabled', False))
    
    def save(self, config_path: Optional[str] = None):
        """
        Save current configuration to file.
        
        Args:
            config_path: Path to save config. If None, uses current config path.
        """
        save_path = Path(config_path) if config_path else self.config_path
        
        if not save_path:
            save_path = Path.cwd() / 'config.yaml'
        
        # Ensure directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(save_path, 'w') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, indent=2)
            
            logger.info(f"Configuration saved to {save_path}")
            self.config_path = save_path
            
        except Exception as e:
            logger.error(f"Error saving config to {save_path}: {e}")
            raise
    
    def create_example_config(self, output_path: str):
        """Create an example configuration file with comments."""
        example_config = """
# reMarkable Integration Configuration

# reMarkable tablet settings
remarkable:
  # Path to reMarkable sync directory (required)
  sync_directory: null  # e.g., "/Users/username/reMarkable"
  # Path to backup directory (optional)
  backup_directory: null

# Database settings
database:
  # Path to SQLite database file
  path: "remarkable_pipeline.db"
  # Enable automatic backups
  backup_enabled: true
  # Backup interval in hours
  backup_interval_hours: 24

# Processing settings
processing:
  # Highlight extraction settings
  highlight_extraction:
    enabled: true
    min_text_length: 8
    text_threshold: 0.4
    min_words: 2
    symbol_ratio_threshold: 0.3
  
  # OCR settings (for handwritten text)
  ocr:
    enabled: false
    language: "en"
    confidence_threshold: 0.7
  
  # File watching settings
  file_watching:
    enabled: true
    watch_patterns:
      - "*.content"
      - "*.rm"
    ignore_patterns:
      - ".*"
      - "*.tmp"

# Third-party integrations
integrations:
  # Notion integration
  notion:
    enabled: false
    api_token: null  # Get from https://developers.notion.com/
    database_id: null
  
  # Readwise integration  
  readwise:
    enabled: false
    api_token: null  # Get from https://readwise.io/access_token
  
  # Microsoft To Do integration
  microsoft_todo:
    enabled: false
    client_id: null
    client_secret: null

# Logging settings
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: null  # null for console only, or path to log file
"""
        
        try:
            with open(output_path, 'w') as f:
                f.write(example_config.strip())
            
            logger.info(f"Example configuration created at {output_path}")
            
        except Exception as e:
            logger.error(f"Error creating example config: {e}")
            raise
    
    def validate(self) -> list:
        """
        Validate configuration and return list of issues.
        
        Returns:
            List of validation error messages
        """
        issues = []
        
        # Check required settings
        sync_dir = self.get('remarkable.sync_directory')
        if not sync_dir:
            issues.append("remarkable.sync_directory is required")
        elif not os.path.exists(sync_dir):
            issues.append(f"remarkable.sync_directory does not exist: {sync_dir}")
        
        # Check database path is writable
        db_path = Path(self.get('database.path'))
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            # Test write access
            test_file = db_path.parent / '.write_test'
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            issues.append(f"Database directory not writable: {e}")
        
        # Validate log level
        log_level = self.get('logging.level')
        if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
            issues.append(f"Invalid logging level: {log_level}")
        
        # Check integration settings
        if self.is_enabled('integrations.notion'):
            if not self.get('integrations.notion.api_token'):
                issues.append("Notion integration enabled but no API token provided")
        
        if self.is_enabled('integrations.readwise'):
            if not self.get('integrations.readwise.api_token'):
                issues.append("Readwise integration enabled but no API token provided")
        
        return issues
    
    def __str__(self) -> str:
        """String representation of configuration."""
        return f"Config(path={self.config_path}, sync_dir={self.get('remarkable.sync_directory')})"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return f"Config(config_path={self.config_path}, data_keys={list(self.config_data.keys())})"