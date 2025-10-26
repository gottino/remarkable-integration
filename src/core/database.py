"""
Database abstraction layer for reMarkable Integration.

Provides a unified interface for database operations and manages connections.
"""

import os
import sqlite3
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Database manager for the reMarkable integration pipeline."""
    
    def __init__(self, db_path: str, backup_enabled: bool = True, backup_interval_hours: int = 24):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
            backup_enabled: Whether to enable automatic backups
            backup_interval_hours: Hours between automatic backups
        """
        self.db_path = Path(db_path).resolve()
        self.backup_enabled = backup_enabled
        self.backup_interval_hours = backup_interval_hours
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._initialize_database()
        
        # Setup backup if enabled
        if backup_enabled:
            self._create_backup_if_needed()
        
        logger.info(f"Database manager initialized: {self.db_path}")
    
    def _initialize_database(self):
        """Initialize database with required tables."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Enable foreign keys
            cursor.execute("PRAGMA foreign_keys = ON")
            
            # Create main tables
            self._create_tables(cursor)
            
            conn.commit()
            logger.debug("Database tables initialized")
    
    def _create_tables(self, cursor):
        """Create all required database tables."""
        
        # Files table - tracks processed files
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                file_type TEXT NOT NULL,  -- 'content', 'rm', 'metadata'
                last_modified TIMESTAMP,
                size_bytes INTEGER,
                checksum TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Notebook metadata table - comprehensive reMarkable metadata
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notebook_metadata (
                notebook_uuid TEXT PRIMARY KEY,
                visible_name TEXT NOT NULL,
                full_path TEXT NOT NULL,
                parent_uuid TEXT,
                item_type TEXT NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'unknown',
                authors TEXT,
                publisher TEXT,
                publication_date TEXT,
                last_modified TEXT,
                last_opened TEXT,
                last_opened_page INTEGER,
                deleted BOOLEAN DEFAULT FALSE,
                pinned BOOLEAN DEFAULT FALSE,
                synced BOOLEAN DEFAULT FALSE,
                version INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add new columns to existing databases if they don't exist
        new_columns = [
            ('document_type', 'TEXT DEFAULT "unknown"'),
            ('authors', 'TEXT'),
            ('publisher', 'TEXT'), 
            ('publication_date', 'TEXT')
        ]
        
        for column_name, column_def in new_columns:
            try:
                cursor.execute(f'ALTER TABLE notebook_metadata ADD COLUMN {column_name} {column_def}')
            except sqlite3.OperationalError:
                # Column already exists, ignore
                pass
        
        # Create indexes for faster lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_notebook_metadata_path 
            ON notebook_metadata(full_path)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_notebook_metadata_last_modified 
            ON notebook_metadata(last_modified)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_notebook_metadata_last_opened 
            ON notebook_metadata(last_opened)
        ''')
        
        # Processing results table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processing_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER,
                processor_type TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                error_message TEXT,
                processing_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        ''')
        
        # Highlights table - basic highlights
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                page_number TEXT,
                file_name TEXT,
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_file, text, page_number) ON CONFLICT IGNORE
            )
        ''')
        
        # Enhanced highlights table - for EPUB-corrected highlights
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS enhanced_highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                title TEXT NOT NULL,
                original_text TEXT NOT NULL,
                corrected_text TEXT NOT NULL,
                page_number TEXT,
                file_name TEXT,
                passage_id INTEGER,
                confidence REAL,
                match_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_file, corrected_text, page_number) ON CONFLICT IGNORE
            )
        ''')
        
        # OCR results table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ocr_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                page_number TEXT,
                text TEXT NOT NULL,
                confidence REAL,
                language TEXT,
                bounding_box TEXT,  -- JSON string for coordinates
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Events table - for event system
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                data TEXT,  -- JSON string
                timestamp TEXT NOT NULL,
                source TEXT,
                correlation_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # TODO: Add todos table for better todo tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notebook_uuid TEXT NOT NULL,
                page_uuid TEXT,
                source_file TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                page_number TEXT,
                completed BOOLEAN DEFAULT FALSE,
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Notebook text extractions table - with incremental update support
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notebook_text_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notebook_uuid TEXT NOT NULL,
                notebook_name TEXT NOT NULL,
                page_uuid TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                text TEXT NOT NULL,
                confidence REAL NOT NULL,
                bounding_box TEXT,
                language TEXT,
                page_content_hash TEXT,  -- For incremental updates
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(notebook_uuid, page_uuid, text, confidence)
            )
        ''')
        
        # Run schema migrations FIRST (before creating indexes that depend on migrated columns)
        self._run_migrations(cursor)
        
        # Create indexes for better performance (after migrations)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_files_path ON files(file_path)",
            "CREATE INDEX IF NOT EXISTS idx_files_modified ON files(last_modified)",
            "CREATE INDEX IF NOT EXISTS idx_highlights_source ON highlights(source_file)",
            "CREATE INDEX IF NOT EXISTS idx_highlights_title ON highlights(title)",
            "CREATE INDEX IF NOT EXISTS idx_enhanced_highlights_source ON enhanced_highlights(source_file)",
            "CREATE INDEX IF NOT EXISTS idx_enhanced_highlights_passage ON enhanced_highlights(passage_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_notebook_extractions_notebook ON notebook_text_extractions(notebook_uuid)",
            "CREATE INDEX IF NOT EXISTS idx_notebook_extractions_page ON notebook_text_extractions(notebook_uuid, page_uuid)",
            "CREATE INDEX IF NOT EXISTS idx_notebook_extractions_hash ON notebook_text_extractions(page_content_hash)",
            "CREATE INDEX IF NOT EXISTS idx_todos_source ON todos(source_file)",
        ]
        
        for index_sql in indexes:
            try:
                cursor.execute(index_sql)
            except sqlite3.OperationalError as e:
                if 'no such column' in str(e):
                    logger.warning(f"Skipping index creation due to missing column: {index_sql}")
                else:
                    raise
    
    def _run_migrations(self, cursor):
        """Run database schema migrations."""
        # Create migrations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL UNIQUE,
                description TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Get current schema version
        cursor.execute('SELECT MAX(version) FROM schema_migrations')
        result = cursor.fetchone()
        current_version = result[0] if result[0] is not None else 0
        
        # Define migrations
        migrations = [
            (1, 'Add page_content_hash to notebook_text_extractions', self._migration_001),
            (2, 'Add updated_at triggers', self._migration_002),
        ]
        
        # Apply pending migrations
        for version, description, migration_func in migrations:
            if version > current_version:
                try:
                    logger.info(f"Applying migration {version}: {description}")
                    migration_func(cursor)
                    
                    # Record migration
                    cursor.execute(
                        'INSERT INTO schema_migrations (version, description) VALUES (?, ?)',
                        (version, description)
                    )
                    
                    logger.info(f"Migration {version} completed successfully")
                    
                except Exception as e:
                    logger.error(f"Migration {version} failed: {e}")
                    raise
    
    def _migration_001(self, cursor):
        """Add page_content_hash column to notebook_text_extractions if it doesn't exist."""
        try:
            cursor.execute('ALTER TABLE notebook_text_extractions ADD COLUMN page_content_hash TEXT')
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                logger.debug("page_content_hash column already exists")
            else:
                raise
    
    def _migration_002(self, cursor):
        """Add triggers to update updated_at timestamps."""
        # Trigger for notebook_text_extractions
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS update_notebook_extractions_timestamp 
            AFTER UPDATE ON notebook_text_extractions
            BEGIN
                UPDATE notebook_text_extractions 
                SET updated_at = CURRENT_TIMESTAMP 
                WHERE id = NEW.id;
            END
        ''')
        
        # Trigger for todos
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS update_todos_timestamp 
            AFTER UPDATE ON todos
            BEGIN
                UPDATE todos 
                SET updated_at = CURRENT_TIMESTAMP 
                WHERE id = NEW.id;
            END
        ''')
    
    def get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection.
        
        Returns:
            SQLite connection object
        """
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")  # 30 second timeout for locks
            conn.execute("PRAGMA journal_mode = WAL")    # Better concurrent access
            conn.row_factory = sqlite3.Row  # Enable column access by name
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    @contextmanager
    def get_connection_context(self):
        """
        Get database connection as context manager.
        
        Yields:
            SQLite connection that will be automatically closed
        """
        conn = None
        try:
            conn = self.get_connection()
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database operation failed: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def execute_query(self, query: str, params: tuple = (), fetch: bool = False) -> List[sqlite3.Row]:
        """
        Execute a SQL query with parameters.
        
        Args:
            query: SQL query string
            params: Query parameters
            fetch: Whether to fetch and return results
            
        Returns:
            Query results if fetch=True, empty list otherwise
        """
        with self.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            if fetch:
                return cursor.fetchall()
            else:
                conn.commit()
                return []
    
    def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Dictionary with database statistics
        """
        with self.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Get table counts
            tables = [
                'files', 'processing_results', 'highlights',
                'enhanced_highlights', 'ocr_results', 'events', 'todos', 'notebook_metadata'
            ]
            
            stats = {
                'database_path': str(self.db_path),
                'database_size_mb': self.db_path.stat().st_size / (1024 * 1024),
                'tables': {}
            }
            
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    stats['tables'][table] = count
                except sqlite3.OperationalError:
                    # Table doesn't exist
                    stats['tables'][table] = 0
            
            # Get recent activity
            try:
                cursor.execute("""
                    SELECT COUNT(*) as recent_events 
                    FROM events 
                    WHERE created_at > datetime('now', '-24 hours')
                """)
                stats['recent_events_24h'] = cursor.fetchone()[0]
            except:
                stats['recent_events_24h'] = 0
            
            return stats
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """
        Clean up old data from the database.
        
        Args:
            days_to_keep: Number of days of data to keep
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        with self.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Clean up old events
            cursor.execute(
                "DELETE FROM events WHERE created_at < ?",
                (cutoff_date,)
            )
            events_deleted = cursor.rowcount
            
            # Clean up old processing results
            cursor.execute(
                "DELETE FROM processing_results WHERE created_at < ?",
                (cutoff_date,)
            )
            results_deleted = cursor.rowcount
            
            conn.commit()
            
            logger.info(f"Cleanup completed: {events_deleted} events, {results_deleted} processing results deleted")
    
    def vacuum(self):
        """Vacuum the database to reclaim space."""
        try:
            with self.get_connection_context() as conn:
                conn.execute("VACUUM")
            logger.info("Database vacuumed successfully")
        except Exception as e:
            logger.error(f"Failed to vacuum database: {e}")
            raise
    
    def _create_backup_if_needed(self):
        """Create database backup if needed."""
        if not self.backup_enabled:
            return
        
        backup_dir = self.db_path.parent / 'backups'
        backup_dir.mkdir(exist_ok=True)
        
        # Check if we need a new backup
        latest_backup = self._get_latest_backup(backup_dir)
        
        if latest_backup:
            backup_age = datetime.now() - datetime.fromtimestamp(latest_backup.stat().st_mtime)
            if backup_age.total_seconds() < (self.backup_interval_hours * 3600):
                logger.debug("Recent backup exists, skipping")
                return
        
        # Create backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{self.db_path.stem}_backup_{timestamp}.db"
        backup_path = backup_dir / backup_name
        
        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"Database backup created: {backup_path}")
            
            # Clean up old backups (keep last 10)
            self._cleanup_old_backups(backup_dir, keep_count=10)
            
        except Exception as e:
            logger.error(f"Failed to create database backup: {e}")
    
    def _get_latest_backup(self, backup_dir: Path) -> Optional[Path]:
        """Get the most recent backup file."""
        backup_pattern = f"{self.db_path.stem}_backup_*.db"
        backups = list(backup_dir.glob(backup_pattern))
        
        if not backups:
            return None
        
        return max(backups, key=lambda p: p.stat().st_mtime)
    
    def _cleanup_old_backups(self, backup_dir: Path, keep_count: int = 10):
        """Remove old backup files, keeping only the most recent ones."""
        backup_pattern = f"{self.db_path.stem}_backup_*.db"
        backups = list(backup_dir.glob(backup_pattern))
        
        if len(backups) <= keep_count:
            return
        
        # Sort by modification time, oldest first
        backups.sort(key=lambda p: p.stat().st_mtime)
        
        # Remove oldest backups
        to_remove = backups[:-keep_count]
        for backup in to_remove:
            try:
                backup.unlink()
                logger.debug(f"Removed old backup: {backup.name}")
            except Exception as e:
                logger.error(f"Failed to remove old backup {backup}: {e}")
    
    def create_backup_manually(self, backup_path: Optional[str] = None) -> str:
        """
        Create a manual backup of the database.
        
        Args:
            backup_path: Path for backup file. If None, creates in backups directory.
            
        Returns:
            Path to created backup file
        """
        if backup_path:
            backup_file = Path(backup_path)
        else:
            backup_dir = self.db_path.parent / 'backups'
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{self.db_path.stem}_manual_{timestamp}.db"
            backup_file = backup_dir / backup_name
        
        try:
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.db_path, backup_file)
            logger.info(f"Manual backup created: {backup_file}")
            return str(backup_file)
            
        except Exception as e:
            logger.error(f"Failed to create manual backup: {e}")
            raise
    
    def restore_from_backup(self, backup_path: str):
        """
        Restore database from backup.
        
        Args:
            backup_path: Path to backup file
        """
        backup_file = Path(backup_path)
        
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
        
        # Create backup of current database before restoring
        current_backup = self.create_backup_manually()
        logger.info(f"Current database backed up to: {current_backup}")
        
        try:
            shutil.copy2(backup_file, self.db_path)
            logger.info(f"Database restored from backup: {backup_path}")
            
        except Exception as e:
            logger.error(f"Failed to restore from backup: {e}")
            raise
    
    def __enter__(self):
        """Context manager entry."""
        self.connection = self.get_connection()
        return self.connection
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if hasattr(self, 'connection'):
            if exc_type:
                self.connection.rollback()
            self.connection.close()
    
    def __str__(self) -> str:
        """String representation."""
        return f"DatabaseManager(db_path={self.db_path})"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return f"DatabaseManager(db_path={self.db_path}, backup_enabled={self.backup_enabled})"