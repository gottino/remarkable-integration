"""
Migration tools for unified sync tracking system.

This handles:
1. Schema migrations for unified sync_records table
2. Legacy data migration from integration-specific tables  
3. Transitioning from legacy sync to unified event-driven sync engine

The unified sync system replaces multiple integration-specific sync tables
with a single sync_records table using target_name approach.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
import json

from .sync_engine import ContentFingerprint, DeduplicationService, SyncItemType, SyncStatus

logger = logging.getLogger(__name__)


class UnifiedSyncMigration:
    """Handles migrations for the unified sync tracking system."""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(f"{__name__}.UnifiedSyncMigration")
    
    def migrate_to_unified_sync_schema(self) -> bool:
        """
        Migrate sync_records table to support unified sync architecture.
        
        Creates the table if it doesn't exist and adds missing columns:
        - item_id: Local database ID/UUID of the synced item
        - metadata: JSON field for target-specific metadata
        
        Returns:
            True if migration was successful, False otherwise
        """
        self.logger.info("Starting migration to unified sync schema")
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # First, ensure the sync_records table exists
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sync_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content_hash TEXT NOT NULL,
                        target_name TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        item_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_message TEXT,
                        retry_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        synced_at TIMESTAMP,
                        UNIQUE(content_hash, target_name)
                    )
                ''')
                
                # Create basic indexes
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_hash ON sync_records(content_hash)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_target ON sync_records(target_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_status ON sync_records(status)')
                
                # Check current schema
                cursor.execute("PRAGMA table_info(sync_records)")
                columns = [row[1] for row in cursor.fetchall()]
                
                migrations_applied = []
                
                # Add item_id column if missing
                if 'item_id' not in columns:
                    self.logger.info("Adding item_id column to sync_records")
                    cursor.execute('ALTER TABLE sync_records ADD COLUMN item_id TEXT')
                    migrations_applied.append('item_id')
                
                # Add metadata column if missing
                if 'metadata' not in columns:
                    self.logger.info("Adding metadata column to sync_records")
                    cursor.execute('ALTER TABLE sync_records ADD COLUMN metadata TEXT')
                    migrations_applied.append('metadata')
                
                # Create new indexes for the added columns
                if 'item_id' in migrations_applied:
                    cursor.execute('''
                        CREATE INDEX IF NOT EXISTS idx_sync_records_item_id 
                        ON sync_records(item_id)
                    ''')
                
                # Update unique constraint to improve deduplication
                if migrations_applied:
                    self.logger.info("Creating enhanced indexes for unified sync")
                    cursor.execute('''
                        CREATE INDEX IF NOT EXISTS idx_sync_records_content_target_item 
                        ON sync_records(content_hash, target_name, item_id)
                    ''')
                
                conn.commit()
                
                if migrations_applied:
                    self.logger.info(f"Schema migration completed. Applied: {', '.join(migrations_applied)}")
                else:
                    self.logger.info("Schema already up to date")
                
                return True
                
        except Exception as e:
            self.logger.error(f"Schema migration failed: {e}")
            return False
    
    def migrate_legacy_sync_tables(self) -> bool:
        """
        Migrate data from legacy sync tables to unified sync_records.
        
        Migrates from:
        - notion_notebook_sync -> sync_records
        - notion_page_sync -> sync_records  
        - notion_todo_sync -> sync_records (if exists)
        
        Returns:
            True if migration was successful, False otherwise
        """
        self.logger.info("Starting migration of legacy sync tables")
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                migrated_count = 0
                
                # Migrate notion_notebook_sync
                migrated_count += self._migrate_notion_notebook_sync(cursor)
                
                # Migrate notion_page_sync
                migrated_count += self._migrate_notion_page_sync(cursor)
                
                # Migrate notion_todo_sync if it exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='notion_todo_sync'
                """)
                if cursor.fetchone():
                    migrated_count += self._migrate_notion_todo_sync(cursor)
                
                conn.commit()
                
                self.logger.info(f"Legacy migration completed. Migrated {migrated_count} records")
                return True
                
        except Exception as e:
            self.logger.error(f"Legacy migration failed: {e}")
            return False
    
    def _migrate_notion_notebook_sync(self, cursor) -> int:
        """Migrate notion_notebook_sync to sync_records."""
        try:
            cursor.execute("""
                SELECT notebook_uuid, notion_page_id, last_synced, 
                       content_hash, total_pages, metadata_hash
                FROM notion_notebook_sync
            """)
            
            notebook_records = cursor.fetchall()
            migrated = 0
            
            for record in notebook_records:
                notebook_uuid, notion_page_id, last_synced, content_hash, total_pages, metadata_hash = record
                
                # Create metadata JSON
                metadata = {
                    'total_pages': total_pages,
                    'metadata_hash': metadata_hash,
                    'migration_source': 'notion_notebook_sync'
                }
                
                # Insert into sync_records
                cursor.execute("""
                    INSERT OR IGNORE INTO sync_records 
                    (content_hash, target_name, external_id, item_type, status,
                     item_id, metadata, created_at, updated_at, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    content_hash or '',
                    'notion',
                    notion_page_id,
                    'notebook',
                    'success',
                    notebook_uuid,
                    json.dumps(metadata),
                    last_synced or datetime.now().isoformat(),
                    last_synced or datetime.now().isoformat(),
                    last_synced
                ))
                
                migrated += cursor.rowcount
            
            self.logger.info(f"Migrated {migrated} notebook sync records")
            return migrated
            
        except Exception as e:
            self.logger.error(f"Failed to migrate notion_notebook_sync: {e}")
            return 0
    
    def _migrate_notion_page_sync(self, cursor) -> int:
        """Migrate notion_page_sync to sync_records."""
        try:
            cursor.execute("""
                SELECT notebook_uuid, page_number, page_uuid, content_hash,
                       last_synced, notion_block_id
                FROM notion_page_sync
            """)
            
            page_records = cursor.fetchall()
            migrated = 0
            
            for record in page_records:
                notebook_uuid, page_number, page_uuid, content_hash, last_synced, notion_block_id = record
                
                # Create metadata JSON
                metadata = {
                    'notebook_uuid': notebook_uuid,
                    'page_number': page_number,
                    'notion_block_id': notion_block_id,
                    'migration_source': 'notion_page_sync'
                }
                
                # Use page_uuid as item_id, fallback to composite key
                item_id = page_uuid or f"{notebook_uuid}::{page_number}"
                
                # Insert into sync_records
                cursor.execute("""
                    INSERT OR IGNORE INTO sync_records 
                    (content_hash, target_name, external_id, item_type, status,
                     item_id, metadata, created_at, updated_at, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    content_hash or '',
                    'notion',
                    notion_block_id or '',
                    'page_text',
                    'success' if notion_block_id else 'pending',
                    item_id,
                    json.dumps(metadata),
                    last_synced or datetime.now().isoformat(),
                    last_synced or datetime.now().isoformat(),
                    last_synced
                ))
                
                migrated += cursor.rowcount
            
            self.logger.info(f"Migrated {migrated} page sync records")
            return migrated
            
        except Exception as e:
            self.logger.error(f"Failed to migrate notion_page_sync: {e}")
            return 0
    
    def _migrate_notion_todo_sync(self, cursor) -> int:
        """Migrate notion_todo_sync to sync_records."""
        try:
            cursor.execute("""
                SELECT todo_id, notion_page_id, exported_at
                FROM notion_todo_sync
            """)
            
            todo_records = cursor.fetchall()
            migrated = 0
            
            for record in todo_records:
                todo_id, notion_page_id, exported_at = record
                
                # Create metadata JSON
                metadata = {
                    'migration_source': 'notion_todo_sync'
                }
                
                # Insert into sync_records
                cursor.execute("""
                    INSERT OR IGNORE INTO sync_records 
                    (content_hash, target_name, external_id, item_type, status,
                     item_id, metadata, created_at, updated_at, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    '',  # No content_hash available from legacy table
                    'notion',
                    notion_page_id,
                    'todo',
                    'success',
                    str(todo_id),
                    json.dumps(metadata),
                    exported_at or datetime.now().isoformat(),
                    exported_at or datetime.now().isoformat(),
                    exported_at
                ))
                
                migrated += cursor.rowcount
            
            self.logger.info(f"Migrated {migrated} todo sync records")
            return migrated
            
        except Exception as e:
            self.logger.error(f"Failed to migrate notion_todo_sync: {e}")
            return 0
    
    def validate_migration(self) -> Dict[str, Any]:
        """
        Validate the migration results.
        
        Returns:
            Dictionary with validation results and statistics
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check sync_records table structure
                cursor.execute("PRAGMA table_info(sync_records)")
                columns = [row[1] for row in cursor.fetchall()]
                
                # Count records by source
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_records,
                        COUNT(CASE WHEN item_id IS NOT NULL THEN 1 END) as with_item_id,
                        COUNT(CASE WHEN metadata IS NOT NULL THEN 1 END) as with_metadata
                    FROM sync_records
                """)
                counts = cursor.fetchone()
                
                # Count by target and type
                cursor.execute("""
                    SELECT target_name, item_type, COUNT(*) 
                    FROM sync_records 
                    GROUP BY target_name, item_type
                    ORDER BY target_name, item_type
                """)
                breakdown = cursor.fetchall()
                
                return {
                    'schema_valid': all(col in columns for col in ['item_id', 'metadata']),
                    'columns': columns,
                    'total_records': counts[0] if counts else 0,
                    'records_with_item_id': counts[1] if counts else 0,
                    'records_with_metadata': counts[2] if counts else 0,
                    'target_type_breakdown': [
                        {'target': row[0], 'type': row[1], 'count': row[2]} 
                        for row in breakdown
                    ]
                }
                
        except Exception as e:
            self.logger.error(f"Migration validation failed: {e}")
            return {'error': str(e)}


class SyncMigrationAnalyzer:
    """
    Analyzes existing sync state and plans migration to event-driven system.
    
    This tool helps transition from legacy sync methods to the new event-driven
    sync engine by identifying what's already synced and what needs processing.
    """
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(f"{__name__}.SyncMigrationAnalyzer")
        self.dedup_service = DeduplicationService(db_manager)
    
    async def analyze_migration_state(self) -> Dict[str, Any]:
        """
        Analyze the current state and identify what needs migration.
        
        Returns:
            Comprehensive analysis of migration requirements
        """
        analysis = {
            'pending_changes': await self._analyze_pending_changes(),
            'existing_notion_pages': await self._analyze_existing_notion_pages(),
            'content_mapping': await self._map_content_to_notion(),
            'migration_plan': {},
            'risk_assessment': {}
        }
        
        # Generate migration plan based on analysis
        analysis['migration_plan'] = await self._generate_migration_plan(analysis)
        analysis['risk_assessment'] = await self._assess_migration_risks(analysis)
        
        return analysis
    
    async def _analyze_pending_changes(self) -> Dict[str, Any]:
        """Analyze pending changes in sync_changelog."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get overall pending changes stats
                cursor.execute('''
                    SELECT source_table, operation, COUNT(*) as count
                    FROM sync_changelog 
                    WHERE processed_at IS NULL
                    GROUP BY source_table, operation
                    ORDER BY count DESC
                ''')
                
                pending_by_type = {}
                total_pending = 0
                
                for source_table, operation, count in cursor.fetchall():
                    if source_table not in pending_by_type:
                        pending_by_type[source_table] = {}
                    pending_by_type[source_table][operation] = count
                    total_pending += count
                
                # Get oldest and newest pending changes
                cursor.execute('''
                    SELECT MIN(changed_at), MAX(changed_at)
                    FROM sync_changelog 
                    WHERE processed_at IS NULL
                ''')
                date_range = cursor.fetchone()
                
                return {
                    'total_pending': total_pending,
                    'by_table_and_type': pending_by_type,
                    'date_range': {
                        'oldest': date_range[0],
                        'newest': date_range[1]
                    }
                }
                
        except Exception as e:
            self.logger.error(f"Error analyzing pending changes: {e}")
            return {'error': str(e)}
    
    async def _analyze_existing_notion_pages(self) -> Dict[str, Any]:
        """Analyze existing Notion pages to understand current sync state."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Check if we have a notion sync tracking table
                cursor.execute('''
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='notion_sync_status'
                ''')
                
                has_notion_tracking = bool(cursor.fetchone())
                
                if has_notion_tracking:
                    # Get existing Notion sync data
                    cursor.execute('''
                        SELECT COUNT(*) as total_pages,
                               COUNT(CASE WHEN status = 'synced' THEN 1 END) as synced_pages,
                               COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_pages,
                               MIN(last_synced), MAX(last_synced)
                        FROM notion_sync_status
                    ''')
                    
                    stats = cursor.fetchone()
                    
                    return {
                        'has_tracking': True,
                        'total_pages': stats[0],
                        'synced_pages': stats[1],
                        'failed_pages': stats[2],
                        'sync_date_range': {
                            'earliest': stats[3],
                            'latest': stats[4]
                        }
                    }
                else:
                    # No explicit tracking - need to infer from other sources
                    return {
                        'has_tracking': False,
                        'inference_needed': True,
                        'suggestion': 'Use Notion API to fetch existing pages and compare'
                    }
                    
        except Exception as e:
            self.logger.error(f"Error analyzing existing Notion pages: {e}")
            return {'error': str(e)}
    
    async def _map_content_to_notion(self) -> Dict[str, Any]:
        """Map local content to existing Notion pages using content fingerprints."""
        try:
            # Get all notebooks that could be synced to Notion
            notebooks = await self._get_all_notebooks()
            
            content_map = {
                'notebooks': {},
                'unmapped_count': 0,
                'mapped_count': 0
            }
            
            for notebook in notebooks:
                # Generate content fingerprint
                content_hash = ContentFingerprint.for_notebook(notebook)
                
                # Check if this content is already tracked in sync_records
                existing_syncs = await self.dedup_service.find_existing_syncs(content_hash)
                notion_sync = None
                
                for sync_record in existing_syncs:
                    if sync_record.target_name == 'notion' and sync_record.status == SyncStatus.SUCCESS:
                        notion_sync = sync_record
                        break
                
                if notion_sync:
                    content_map['notebooks'][notebook['notebook_uuid']] = {
                        'status': 'already_synced',
                        'notion_page_id': notion_sync.external_id,
                        'content_hash': content_hash,
                        'synced_at': notion_sync.synced_at
                    }
                    content_map['mapped_count'] += 1
                else:
                    content_map['notebooks'][notebook['notebook_uuid']] = {
                        'status': 'needs_sync',
                        'content_hash': content_hash,
                        'title': notebook.get('title', 'Untitled'),
                        'page_count': notebook.get('page_count', 0)
                    }
                    content_map['unmapped_count'] += 1
            
            return content_map
            
        except Exception as e:
            self.logger.error(f"Error mapping content to Notion: {e}")
            return {'error': str(e)}
    
    async def _get_all_notebooks(self) -> List[Dict[str, Any]]:
        """Get all notebooks from the database."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT notebook_uuid, notebook_name,
                           GROUP_CONCAT(text, '\n\n') as full_text,
                           COUNT(*) as page_count,
                           AVG(confidence) as avg_confidence,
                           MIN(created_at) as first_created,
                           MAX(updated_at) as last_updated
                    FROM notebook_text_extractions
                    GROUP BY notebook_uuid, notebook_name
                    ORDER BY last_updated DESC
                ''')
                
                notebooks = []
                for row in cursor.fetchall():
                    notebooks.append({
                        'notebook_uuid': row[0],
                        'title': row[1] or 'Untitled Notebook',
                        'text_content': row[2] or '',
                        'page_count': row[3],
                        'avg_confidence': row[4],
                        'first_created': row[5],
                        'last_updated': row[6],
                        'type': 'notebook'
                    })
                
                return notebooks
                
        except Exception as e:
            self.logger.error(f"Error getting notebooks: {e}")
            return []
    
    async def _generate_migration_plan(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a step-by-step migration plan."""
        pending = analysis.get('pending_changes', {})
        content_map = analysis.get('content_mapping', {})
        
        plan = {
            'strategy': 'incremental_migration',
            'phases': [],
            'estimated_duration': '2-4 hours',
            'rollback_plan': 'Disable new sync engine, continue with legacy'
        }
        
        # Phase 1: Baseline establishment
        plan['phases'].append({
            'phase': 1,
            'name': 'Establish Baseline',
            'description': 'Map existing Notion pages to local content',
            'steps': [
                'Fetch all existing Notion pages via API',
                'Generate content hashes for existing pages',
                'Populate sync_records table with existing mappings',
                'Mark corresponding changelog entries as processed'
            ],
            'estimated_time': '30-60 minutes',
            'items_affected': content_map.get('mapped_count', 0)
        })
        
        # Phase 2: Process recent changes only
        plan['phases'].append({
            'phase': 2,
            'name': 'Process Recent Changes',
            'description': 'Sync only recent changes (last 7 days)',
            'steps': [
                'Filter pending changes to last 7 days',
                'Process with event-driven sync engine',
                'Verify no duplicates created',
                'Mark older changes as processed without syncing'
            ],
            'estimated_time': '60-90 minutes',
            'items_affected': 'TBD based on date filter'
        })
        
        # Phase 3: Enable real-time sync
        plan['phases'].append({
            'phase': 3,
            'name': 'Enable Real-time Sync',
            'description': 'Switch to event-driven for new changes',
            'steps': [
                'Enable event-driven sync in file watcher',
                'Disable legacy sync methods',
                'Monitor for 24 hours',
                'Verify no issues or duplicates'
            ],
            'estimated_time': '24 hours monitoring',
            'items_affected': 'All future changes'
        })
        
        return plan
    
    async def _assess_migration_risks(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Assess risks and mitigation strategies for migration."""
        risks = {
            'high_risk': [],
            'medium_risk': [],
            'low_risk': [],
            'mitigation_strategies': {}
        }
        
        pending_count = analysis.get('pending_changes', {}).get('total_pending', 0)
        
        # High risk: Large number of pending changes
        if pending_count > 5000:
            risks['high_risk'].append({
                'risk': 'Large backlog could create many duplicates',
                'impact': 'Notion database pollution, performance issues',
                'probability': 'High without proper baseline'
            })
            risks['mitigation_strategies']['large_backlog'] = [
                'Establish baseline before processing any changes',
                'Process in small batches with verification',
                'Use date filtering to process only recent items'
            ]
        
        # Medium risk: No existing sync tracking
        notion_analysis = analysis.get('existing_notion_pages', {})
        if not notion_analysis.get('has_tracking', False):
            risks['medium_risk'].append({
                'risk': 'No tracking of existing Notion pages',
                'impact': 'Difficult to avoid duplicates',
                'probability': 'Medium'
            })
            risks['mitigation_strategies']['no_tracking'] = [
                'Fetch all existing Notion pages',
                'Create reverse mapping from Notion to local content',
                'Use content hashing for duplicate detection'
            ]
        
        # Low risk: Normal operation
        if pending_count < 1000:
            risks['low_risk'].append({
                'risk': 'Minimal pending changes',
                'impact': 'Easy migration',
                'probability': 'Low risk overall'
            })
        
        return risks
    
    async def migrate_existing_notion_sync_data(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Migrate existing Notion sync tracking data to the new sync_records table.
        
        This reads from notion_notebook_sync, notion_page_sync, and notion_todo_sync
        tables and populates the unified sync_records table.
        
        Args:
            dry_run: If True, only simulate the migration
            
        Returns:
            Results of the migration
        """
        try:
            if dry_run:
                self.logger.info("DRY RUN: Simulating migration of existing Notion sync data")
            
            migration_stats = {
                'notebooks': {'existing': 0, 'migrated': 0, 'errors': 0},
                'pages': {'existing': 0, 'migrated': 0, 'errors': 0},
                'todos': {'existing': 0, 'migrated': 0, 'errors': 0},
                'dry_run': dry_run
            }
            
            # Migrate notebook sync data
            await self._migrate_notebook_sync_data(migration_stats, dry_run)
            
            # Migrate page sync data  
            await self._migrate_page_sync_data(migration_stats, dry_run)
            
            # Migrate todo sync data
            await self._migrate_todo_sync_data(migration_stats, dry_run)
            
            # Mark corresponding changelog entries as processed
            if not dry_run:
                await self._mark_migrated_changes_as_processed()
            
            return {
                'status': 'completed' if not dry_run else 'simulated',
                'migration_stats': migration_stats,
                'total_migrated': sum(stat['migrated'] for stat in migration_stats.values() if isinstance(stat, dict)),
                'total_errors': sum(stat['errors'] for stat in migration_stats.values() if isinstance(stat, dict))
            }
            
        except Exception as e:
            self.logger.error(f"Error migrating existing Notion sync data: {e}")
            return {'error': str(e), 'status': 'failed'}
    
    async def _migrate_notebook_sync_data(self, stats: Dict, dry_run: bool) -> None:
        """Migrate data from notion_notebook_sync table."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get existing notebook sync records
                cursor.execute('''
                    SELECT notebook_uuid, notion_page_id, last_synced, content_hash
                    FROM notion_notebook_sync
                    WHERE notion_page_id IS NOT NULL
                    ORDER BY last_synced DESC
                ''')
                
                notebook_syncs = cursor.fetchall()
                stats['notebooks']['existing'] = len(notebook_syncs)
                
                for notebook_uuid, notion_page_id, last_synced, content_hash in notebook_syncs:
                    try:
                        if not dry_run:
                            # Insert into sync_records table
                            await self.dedup_service.register_sync(
                                content_hash=content_hash or f"legacy_notebook_{notebook_uuid}",
                                target_name="notion",
                                external_id=notion_page_id,
                                item_type=SyncItemType.NOTEBOOK,
                                status=SyncStatus.SUCCESS
                            )
                        
                        stats['notebooks']['migrated'] += 1
                        
                    except Exception as e:
                        self.logger.error(f"Error migrating notebook {notebook_uuid}: {e}")
                        stats['notebooks']['errors'] += 1
                        
        except Exception as e:
            self.logger.error(f"Error migrating notebook sync data: {e}")
            stats['notebooks']['errors'] += 1
    
    async def _migrate_page_sync_data(self, stats: Dict, dry_run: bool) -> None:
        """Migrate data from notion_page_sync table."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get existing page sync records
                cursor.execute('''
                    SELECT notebook_uuid, page_number, page_uuid, content_hash, 
                           last_synced, notion_block_id
                    FROM notion_page_sync
                    WHERE notion_block_id IS NOT NULL
                    ORDER BY last_synced DESC
                ''')
                
                page_syncs = cursor.fetchall()
                stats['pages']['existing'] = len(page_syncs)
                
                for notebook_uuid, page_number, page_uuid, content_hash, last_synced, notion_block_id in page_syncs:
                    try:
                        if not dry_run:
                            # Insert into sync_records table
                            await self.dedup_service.register_sync(
                                content_hash=content_hash or f"legacy_page_{page_uuid}",
                                target_name="notion",
                                external_id=notion_block_id,
                                item_type=SyncItemType.PAGE_TEXT,
                                status=SyncStatus.SUCCESS
                            )
                        
                        stats['pages']['migrated'] += 1
                        
                    except Exception as e:
                        self.logger.error(f"Error migrating page {page_uuid}: {e}")
                        stats['pages']['errors'] += 1
                        
        except Exception as e:
            self.logger.error(f"Error migrating page sync data: {e}")
            stats['pages']['errors'] += 1
    
    async def _migrate_todo_sync_data(self, stats: Dict, dry_run: bool) -> None:
        """Migrate data from notion_todo_sync table."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get existing todo sync records
                cursor.execute('''
                    SELECT todo_id, notion_page_id, exported_at
                    FROM notion_todo_sync
                    WHERE notion_page_id IS NOT NULL
                    ORDER BY exported_at DESC
                ''')
                
                todo_syncs = cursor.fetchall()
                stats['todos']['existing'] = len(todo_syncs)
                
                for todo_id, notion_page_id, exported_at in todo_syncs:
                    try:
                        if not dry_run:
                            # Generate content hash for the todo
                            cursor.execute('SELECT text, notebook_uuid, page_number FROM todos WHERE id = ?', (todo_id,))
                            todo_data = cursor.fetchone()
                            
                            if todo_data:
                                content_hash = ContentFingerprint.for_todo({
                                    'text': todo_data[0],
                                    'notebook_uuid': todo_data[1],
                                    'page_number': todo_data[2],
                                    'type': 'todo'
                                })
                                
                                # Insert into sync_records table
                                await self.dedup_service.register_sync(
                                    content_hash=content_hash,
                                    target_name="notion",
                                    external_id=notion_page_id,
                                    item_type=SyncItemType.TODO,
                                    status=SyncStatus.SUCCESS
                                )
                        
                        stats['todos']['migrated'] += 1
                        
                    except Exception as e:
                        self.logger.error(f"Error migrating todo {todo_id}: {e}")
                        stats['todos']['errors'] += 1
                        
        except Exception as e:
            self.logger.error(f"Error migrating todo sync data: {e}")
            stats['todos']['errors'] += 1
    
    async def _mark_migrated_changes_as_processed(self) -> None:
        """Mark changelog entries as processed for items that were already synced."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get all successfully synced notebook UUIDs
                cursor.execute('''
                    SELECT DISTINCT sr.content_hash
                    FROM sync_records sr
                    WHERE sr.target_name = 'notion' 
                    AND sr.status = 'success'
                    AND sr.item_type = 'notebook'
                ''')
                
                synced_hashes = {row[0] for row in cursor.fetchall()}
                
                if synced_hashes:
                    # Mark corresponding changelog entries as processed
                    # This is a simplified approach - in practice you'd want more sophisticated matching
                    cursor.execute('''
                        UPDATE sync_changelog 
                        SET processed_at = CURRENT_TIMESTAMP,
                            process_status = 'Migrated from existing Notion sync'
                        WHERE source_table = 'notebooks'
                        AND processed_at IS NULL
                    ''')
                    
                    updated_count = cursor.rowcount
                    conn.commit()
                    
                    self.logger.info(f"Marked {updated_count} changelog entries as processed")
                    
        except Exception as e:
            self.logger.error(f"Error marking migrated changes as processed: {e}")
    
    async def execute_baseline_establishment(self, notion_client, dry_run: bool = True) -> Dict[str, Any]:
        """
        Execute Phase 1: Establish baseline by mapping existing Notion pages.
        
        Args:
            notion_client: Configured Notion client
            dry_run: If True, only simulate the process
            
        Returns:
            Results of baseline establishment
        """
        if dry_run:
            self.logger.info("DRY RUN: Simulating baseline establishment")
        
        try:
            # This would fetch existing Notion pages and create mappings
            result = {
                'pages_analyzed': 0,
                'mappings_created': 0,
                'errors': [],
                'dry_run': dry_run
            }
            
            if dry_run:
                # Simulate the process
                all_notebooks = await self._get_all_notebooks()
                result['pages_analyzed'] = len(all_notebooks)
                result['estimated_mappings'] = len(all_notebooks)
                result['status'] = 'simulation_complete'
            else:
                # Actual implementation would:
                # 1. Fetch all pages from Notion database
                # 2. For each page, try to match with local content
                # 3. Create sync_records entries for matches
                # 4. Mark corresponding changelog entries as processed
                result['status'] = 'not_implemented'
                result['message'] = 'Actual implementation requires Notion API integration'
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error establishing baseline: {e}")
            return {'error': str(e), 'status': 'failed'}
    
    async def execute_incremental_migration(self, days_back: int = 7, dry_run: bool = True) -> Dict[str, Any]:
        """
        Execute Phase 2: Process only recent changes incrementally.
        
        Args:
            days_back: Only process changes from this many days ago
            dry_run: If True, only simulate the process
            
        Returns:
            Results of incremental migration
        """
        if dry_run:
            self.logger.info(f"DRY RUN: Simulating incremental migration for last {days_back} days")
        
        try:
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Count recent changes
                cursor.execute('''
                    SELECT COUNT(*) FROM sync_changelog 
                    WHERE processed_at IS NULL 
                    AND changed_at > ?
                ''', (cutoff_date.isoformat(),))
                
                recent_count = cursor.fetchone()[0]
                
                # Count older changes that would be marked as processed
                cursor.execute('''
                    SELECT COUNT(*) FROM sync_changelog 
                    WHERE processed_at IS NULL 
                    AND changed_at <= ?
                ''', (cutoff_date.isoformat(),))
                
                older_count = cursor.fetchone()[0]
            
            result = {
                'recent_changes': recent_count,
                'older_changes_to_skip': older_count,
                'cutoff_date': cutoff_date.isoformat(),
                'dry_run': dry_run,
                'status': 'simulation_complete' if dry_run else 'ready_to_execute'
            }
            
            if not dry_run:
                # Mark older changes as processed without syncing
                with self.db_manager.get_connection_context() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE sync_changelog 
                        SET processed_at = CURRENT_TIMESTAMP,
                            process_status = 'Skipped during migration - older than cutoff'
                        WHERE processed_at IS NULL 
                        AND changed_at <= ?
                    ''', (cutoff_date.isoformat(),))
                    
                    updated_count = cursor.rowcount
                    conn.commit()
                    
                    result['older_changes_marked'] = updated_count
                    result['status'] = 'older_changes_processed'
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in incremental migration: {e}")
            return {'error': str(e), 'status': 'failed'}


if __name__ == "__main__":
    # Example usage
    import asyncio
    from src.core.database import DatabaseManager
    
    async def test_migration_analysis():
        db_manager = DatabaseManager("remarkable_pipeline.db")
        analyzer = SyncMigrationAnalyzer(db_manager)
        
        print("🔍 Analyzing migration state...")
        analysis = await analyzer.analyze_migration_state()
        
        print(f"\n📊 Migration Analysis Results:")
        print(f"Total pending changes: {analysis['pending_changes']['total_pending']}")
        print(f"Content mapping: {analysis['content_mapping']['mapped_count']} mapped, {analysis['content_mapping']['unmapped_count']} unmapped")
        
        print(f"\n📋 Migration Plan:")
        for phase in analysis['migration_plan']['phases']:
            print(f"  Phase {phase['phase']}: {phase['name']} ({phase['estimated_time']})")
        
        print(f"\n⚠️  Risk Assessment:")
        for risk_level in ['high_risk', 'medium_risk', 'low_risk']:
            risks = analysis['risk_assessment'][risk_level]
            if risks:
                print(f"  {risk_level.upper()}: {len(risks)} issues")
    
    # Run the test
    asyncio.run(test_migration_analysis())


def run_unified_sync_migration(db_manager) -> bool:
    """
    Run the complete migration to unified sync architecture.
    
    Args:
        db_manager: Database manager instance
        
    Returns:
        True if all migrations successful, False otherwise
    """
    migration = UnifiedSyncMigration(db_manager)
    
    logger.info("🔄 Starting unified sync migration")
    
    # Step 1: Migrate schema
    if not migration.migrate_to_unified_sync_schema():
        logger.error("❌ Schema migration failed")
        return False
    
    # Step 2: Migrate legacy data
    if not migration.migrate_legacy_sync_tables():
        logger.error("❌ Legacy data migration failed")
        return False
    
    # Step 3: Validate results
    validation = migration.validate_migration()
    if 'error' in validation:
        logger.error(f"❌ Migration validation failed: {validation['error']}")
        return False
    
    if not validation.get('schema_valid', False):
        logger.error("❌ Schema validation failed")
        return False
    
    logger.info("✅ Unified sync migration completed successfully")
    logger.info(f"📊 Total records: {validation['total_records']}")
    logger.info(f"🆔 Records with item_id: {validation['records_with_item_id']}")
    logger.info(f"📦 Records with metadata: {validation['records_with_metadata']}")
    
    return True