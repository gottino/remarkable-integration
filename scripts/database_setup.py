#!/usr/bin/env python3
"""
Database setup and initialization script for reMarkable Pipeline

This script:
1. Creates the SQLite database with all required tables
2. Sets up proper indexes for performance
3. Initializes configuration and sample data
4. Provides database management utilities
5. Handles database migrations and upgrades
"""

import os
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseSetup:
    """Database setup and initialization manager."""
    
    def __init__(self, db_path: str = "data/remarkable_pipeline.db"):
        """Initialize database setup manager."""
        self.db_path = Path(db_path)
        self.db_dir = self.db_path.parent
        
        # Ensure database directory exists
        self.db_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Database path: {self.db_path.absolute()}")
    
    def setup_database(self, force_recreate: bool = False) -> bool:
        """
        Set up the complete database schema.
        
        Args:
            force_recreate: If True, drop and recreate all tables
            
        Returns:
            True if setup was successful, False otherwise
        """
        try:
            if force_recreate and self.db_path.exists():
                logger.warning("Recreating database - all data will be lost!")
                self.db_path.unlink()
            
            with sqlite3.connect(self.db_path) as conn:
                # Enable foreign keys
                conn.execute("PRAGMA foreign_keys = ON")
                
                # Create all tables
                self._create_file_tracking_table(conn)
                self._create_processing_results_table(conn)
                self._create_highlights_table(conn)
                self._create_todos_table(conn)
                self._create_transcriptions_table(conn)
                self._create_events_table(conn)
                self._create_integrations_table(conn)
                self._create_config_table(conn)
                
                # Create indexes for performance
                self._create_indexes(conn)
                
                # Insert initial configuration
                self._initialize_config(conn)
                
                conn.commit()
                logger.info("✅ Database setup completed successfully")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Database setup failed: {e}")
            return False
    
    def _create_file_tracking_table(self, conn: sqlite3.Connection):
        """Create table for tracking processed files."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS file_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER,
                file_hash TEXT,
                last_modified TIMESTAMP,
                first_processed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_processed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processing_status TEXT DEFAULT 'pending',
                error_message TEXT,
                metadata JSON
            )
        ''')
        logger.debug("Created file_tracking table")
    
    def _create_processing_results_table(self, conn: sqlite3.Connection):
        """Create table for storing processing results."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS processing_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                processor_type TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                processing_time REAL,
                result_data JSON,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES file_tracking (id) ON DELETE CASCADE
            )
        ''')
        logger.debug("Created processing_results table")
    
    def _create_highlights_table(self, conn: sqlite3.Connection):
        """Create table for storing extracted highlights."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER,
                source_file TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                page_number TEXT,
                file_name TEXT,
                confidence REAL DEFAULT 1.0,
                highlight_type TEXT DEFAULT 'text',
                color TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_status JSON,
                FOREIGN KEY (file_id) REFERENCES file_tracking (id) ON DELETE SET NULL
            )
        ''')
        logger.debug("Created highlights table")
    
    def _create_todos_table(self, conn: sqlite3.Connection):
        """Create table for storing detected todos."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER,
                source_file TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                page_number TEXT,
                completed BOOLEAN DEFAULT FALSE,
                priority TEXT DEFAULT 'normal',
                due_date DATE,
                confidence REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_status JSON,
                FOREIGN KEY (file_id) REFERENCES file_tracking (id) ON DELETE SET NULL
            )
        ''')
        logger.debug("Created todos table")
    
    def _create_transcriptions_table(self, conn: sqlite3.Connection):
        """Create table for storing OCR transcriptions."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS transcriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER,
                source_file TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                page_number TEXT,
                confidence REAL DEFAULT 1.0,
                ocr_engine TEXT,
                language TEXT,
                bounding_box JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_status JSON,
                FOREIGN KEY (file_id) REFERENCES file_tracking (id) ON DELETE SET NULL
            )
        ''')
        logger.debug("Created transcriptions table")
    
    def _create_events_table(self, conn: sqlite3.Connection):
        """Create table for storing system events."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                data JSON,
                timestamp TEXT NOT NULL,
                source TEXT,
                correlation_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        logger.debug("Created events table")
    
    def _create_integrations_table(self, conn: sqlite3.Connection):
        """Create table for tracking integration sync status."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS integration_sync (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                integration_name TEXT NOT NULL,
                content_type TEXT NOT NULL,  -- 'highlight', 'todo', 'transcription'
                content_id INTEGER NOT NULL,
                external_id TEXT,
                sync_status TEXT DEFAULT 'pending',  -- 'pending', 'synced', 'failed'
                last_sync_attempt TIMESTAMP,
                last_successful_sync TIMESTAMP,
                error_message TEXT,
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        logger.debug("Created integration_sync table")
    
    def _create_config_table(self, conn: sqlite3.Connection):
        """Create table for storing configuration."""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value JSON NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        logger.debug("Created config table")
    
    def _create_indexes(self, conn: sqlite3.Connection):
        """Create database indexes for better performance."""
        indexes = [
            # File tracking indexes
            "CREATE INDEX IF NOT EXISTS idx_file_tracking_path ON file_tracking (file_path)",
            "CREATE INDEX IF NOT EXISTS idx_file_tracking_type ON file_tracking (file_type)",
            "CREATE INDEX IF NOT EXISTS idx_file_tracking_status ON file_tracking (processing_status)",
            "CREATE INDEX IF NOT EXISTS idx_file_tracking_modified ON file_tracking (last_modified)",
            
            # Processing results indexes
            "CREATE INDEX IF NOT EXISTS idx_processing_file_processor ON processing_results (file_id, processor_type)",
            "CREATE INDEX IF NOT EXISTS idx_processing_success ON processing_results (success)",
            "CREATE INDEX IF NOT EXISTS idx_processing_created ON processing_results (created_at)",
            
            # Highlights indexes
            "CREATE INDEX IF NOT EXISTS idx_highlights_title ON highlights (title)",
            "CREATE INDEX IF NOT EXISTS idx_highlights_source ON highlights (source_file)",
            "CREATE INDEX IF NOT EXISTS idx_highlights_page ON highlights (page_number)",
            "CREATE INDEX IF NOT EXISTS idx_highlights_created ON highlights (created_at)",
            
            # Todos indexes
            "CREATE INDEX IF NOT EXISTS idx_todos_title ON todos (title)",
            "CREATE INDEX IF NOT EXISTS idx_todos_completed ON todos (completed)",
            "CREATE INDEX IF NOT EXISTS idx_todos_due ON todos (due_date)",
            "CREATE INDEX IF NOT EXISTS idx_todos_priority ON todos (priority)",
            
            # Transcriptions indexes
            "CREATE INDEX IF NOT EXISTS idx_transcriptions_title ON transcriptions (title)",
            "CREATE INDEX IF NOT EXISTS idx_transcriptions_engine ON transcriptions (ocr_engine)",
            "CREATE INDEX IF NOT EXISTS idx_transcriptions_confidence ON transcriptions (confidence)",
            
            # Events indexes
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type)",
            "CREATE INDEX IF NOT EXISTS idx_events_source ON events (source)",
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_events_correlation ON events (correlation_id)",
            
            # Integration sync indexes
            "CREATE INDEX IF NOT EXISTS idx_integration_name_type ON integration_sync (integration_name, content_type)",
            "CREATE INDEX IF NOT EXISTS idx_integration_content ON integration_sync (content_type, content_id)",
            "CREATE INDEX IF NOT EXISTS idx_integration_status ON integration_sync (sync_status)",
            "CREATE INDEX IF NOT EXISTS idx_integration_last_sync ON integration_sync (last_successful_sync)"
        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
        
        logger.debug("Created database indexes")
    
    def _initialize_config(self, conn: sqlite3.Connection):
        """Initialize default configuration values."""
        default_config = {
            'database_version': {
                'value': '1.0.0',
                'description': 'Current database schema version'
            },
            'setup_date': {
                'value': datetime.now().isoformat(),
                'description': 'When the database was first set up'
            },
            'highlight_extraction': {
                'value': {
                    'min_text_length': 10,
                    'text_threshold': 0.6,
                    'min_words': 3,
                    'symbol_ratio_threshold': 0.2
                },
                'description': 'Highlight extraction configuration'
            },
            'integrations': {
                'value': {
                    'readwise': {'enabled': False, 'api_key': None},
                    'notion': {'enabled': False, 'api_key': None, 'database_id': None},
                    'microsoft_todo': {'enabled': False, 'client_id': None}
                },
                'description': 'Integration service configurations'
            },
            'sync_directory': {
                'value': None,
                'description': 'Path to reMarkable sync directory'
            }
        }
        
        for key, config in default_config.items():
            conn.execute('''
                INSERT OR IGNORE INTO config (key, value, description)
                VALUES (?, ?, ?)
            ''', (key, json.dumps(config['value']), config['description']))
        
        logger.debug("Initialized default configuration")
    
    def get_database_info(self) -> Dict:
        """Get information about the current database."""
        if not self.db_path.exists():
            return {'exists': False}
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Get table information
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """)
                tables = [row[0] for row in cursor.fetchall()]
                
                # Get row counts
                table_counts = {}
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    table_counts[table] = cursor.fetchone()[0]
                
                # Get database size
                db_size = self.db_path.stat().st_size
                
                # Get configuration
                cursor.execute("SELECT key, value FROM config")
                config = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
                
                return {
                    'exists': True,
                    'path': str(self.db_path.absolute()),
                    'size_bytes': db_size,
                    'size_mb': round(db_size / 1024 / 1024, 2),
                    'tables': tables,
                    'table_counts': table_counts,
                    'config': config
                }
                
        except Exception as e:
            return {'exists': True, 'error': str(e)}
    
    def export_data(self, output_dir: str) -> bool:
        """Export all data to CSV files."""
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            with sqlite3.connect(self.db_path) as conn:
                # Get all tables
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """)
                tables = [row[0] for row in cursor.fetchall()]
                
                # Export each table
                for table in tables:
                    cursor.execute(f"SELECT * FROM {table}")
                    rows = cursor.fetchall()
                    
                    if rows:
                        # Get column names
                        columns = [description[0] for description in cursor.description]
                        
                        # Write CSV
                        import csv
                        csv_path = output_path / f"{table}.csv"
                        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow(columns)
                            writer.writerows(rows)
                        
                        logger.info(f"Exported {len(rows)} rows from {table} to {csv_path}")
                
                logger.info(f"✅ Data export completed to {output_path}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Data export failed: {e}")
            return False
    
    def vacuum_database(self) -> bool:
        """Optimize database by running VACUUM."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("VACUUM")
                logger.info("✅ Database vacuum completed")
                return True
        except Exception as e:
            logger.error(f"❌ Database vacuum failed: {e}")
            return False


def main():
    """Main CLI interface for database setup."""
    import argparse
    
    parser = argparse.ArgumentParser(description="reMarkable Pipeline Database Setup")
    parser.add_argument(
        "--db-path", 
        default="remarkable_pipeline.db",
        help="Path to the database file"
    )
    parser.add_argument(
        "--setup", 
        action="store_true",
        help="Set up the database with all tables"
    )
    parser.add_argument(
        "--force-recreate", 
        action="store_true",
        help="Force recreate the database (WARNING: deletes all data)"
    )
    parser.add_argument(
        "--info", 
        action="store_true",
        help="Show database information"
    )
    parser.add_argument(
        "--export", 
        help="Export all data to CSV files in specified directory"
    )
    parser.add_argument(
        "--vacuum", 
        action="store_true",
        help="Optimize database with VACUUM"
    )
    
    args = parser.parse_args()
    
    # Initialize database setup
    db_setup = DatabaseSetup(args.db_path)
    
    if args.setup:
        success = db_setup.setup_database(force_recreate=args.force_recreate)
        if not success:
            exit(1)
    
    if args.info:
        info = db_setup.get_database_info()
        print("\n📊 Database Information:")
        print("=" * 50)
        
        if not info.get('exists'):
            print("❌ Database does not exist. Run with --setup to create it.")
            return
        
        if 'error' in info:
            print(f"❌ Error reading database: {info['error']}")
            return
        
        print(f"📍 Path: {info['path']}")
        print(f"💾 Size: {info['size_mb']} MB ({info['size_bytes']} bytes)")
        print(f"🗃️ Tables: {len(info['tables'])}")
        
        print(f"\n📋 Table Contents:")
        for table, count in info['table_counts'].items():
            print(f"  {table}: {count} rows")
        
        if info['config']:
            print(f"\n⚙️ Configuration:")
            for key, value in info['config'].items():
                if isinstance(value, dict) and len(str(value)) > 100:
                    print(f"  {key}: {type(value).__name__} (complex)")
                else:
                    print(f"  {key}: {value}")
    
    if args.export:
        success = db_setup.export_data(args.export)
        if not success:
            exit(1)
    
    if args.vacuum:
        success = db_setup.vacuum_database()
        if not success:
            exit(1)
    
    if not any([args.setup, args.info, args.export, args.vacuum]):
        print("No action specified. Use --help for options.")
        print("Quick start: python database_setup.py --setup --info")


if __name__ == "__main__":
    main()
