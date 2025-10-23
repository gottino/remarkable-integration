"""
File Watching System for reMarkable Integration

Implements a two-tier watching system:
1. SourceWatcher - Monitors the original reMarkable app directory
2. ProcessingWatcher - Monitors the source directory for processing

This approach provides real-time responsiveness while maintaining processing reliability.
"""

import os
import asyncio
import logging
import hashlib
import subprocess
from pathlib import Path
from typing import Optional, Callable, Dict, List, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
from ..processors.notebook_text_extractor import NotebookProcessingResult

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .events import get_event_bus, EventType, publish_file_event
from .unified_sync import UnifiedSyncManager
from ..utils.config import Config

logger = logging.getLogger(__name__)


@dataclass
class SyncEvent:
    """Represents a sync operation that needs to be performed."""
    source_path: str
    target_path: str
    event_type: str  # 'created', 'modified', 'deleted'
    timestamp: datetime
    

# NOTE: SyncManager disabled - processing now happens directly from source directory
# class SyncManager:
#     """Manages rsync operations between source and target directories."""
    
    def __init__(self, config: Config):
        self.config = config
        self.source_dir = Path(config.get('remarkable.source_directory', ''))
        self.target_dir = Path(config.get('remarkable.local_sync_directory', './data/remarkable_sync'))
        self.debounce_seconds = config.get('remarkable.sync_debounce_seconds', 30)
        self.exclude_patterns = config.get('remarkable.sync_exclude_patterns', [])
        
        self._pending_sync = False
        self._last_sync_time = None
        self._sync_lock = asyncio.Lock()
        
        # Ensure target directory exists
        self.target_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"SyncManager initialized: {self.source_dir} -> {self.target_dir}")
    
    async def sync_if_needed(self, force: bool = False) -> bool:
        """Perform sync if needed, with debouncing."""
        async with self._sync_lock:
            now = datetime.now()
            
            # Check if we should skip due to debouncing
            if not force and self._last_sync_time:
                time_since_last = now - self._last_sync_time
                if time_since_last.total_seconds() < self.debounce_seconds:
                    self._pending_sync = True
                    logger.debug(f"Sync debounced, waiting {self.debounce_seconds}s")
                    return False
            
            if not self.source_dir.exists():
                logger.error(f"Source directory does not exist: {self.source_dir}")
                return False
            
            try:
                logger.info("Starting rsync operation...")
                result = await self._perform_rsync()
                
                if result:
                    self._last_sync_time = now
                    self._pending_sync = False
                    logger.info("Rsync completed successfully")
                    
                    # Publish sync event
                    event_bus = get_event_bus()
                    event_bus.emit(EventType.SYNC_DETECTED, {
                        'source_dir': str(self.source_dir),
                        'target_dir': str(self.target_dir),
                        'timestamp': now.isoformat()
                    })
                    
                return result
                
            except Exception as e:
                logger.error(f"Rsync failed: {e}")
                return False
    
    async def _perform_rsync(self) -> bool:
        """Perform the actual rsync operation."""
        try:
            # Build rsync command
            cmd = [
                'rsync', 
                '-av',  # archive mode, verbose
                '--delete',  # delete files not in source
                '--progress'
            ]
            
            # Add exclude patterns
            for pattern in self.exclude_patterns:
                cmd.extend(['--exclude', pattern])
            
            # Add source and target (ensure trailing slash for source)
            cmd.append(f"{self.source_dir}/")
            cmd.append(str(self.target_dir))
            
            logger.debug(f"Running rsync command: {' '.join(cmd)}")
            
            # Run rsync asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                if stdout:
                    logger.debug(f"Rsync output: {stdout.decode()}")
                return True
            else:
                logger.error(f"Rsync failed with code {process.returncode}: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Error running rsync: {e}")
            return False
    
    async def schedule_delayed_sync(self):
        """Schedule a sync after debounce period if one is pending."""
        if self._pending_sync:
            await asyncio.sleep(self.debounce_seconds)
            if self._pending_sync:  # Still pending after delay
                await self.sync_if_needed(force=True)


class SourceWatcher:
    """Watches the original reMarkable app directory for changes."""
    
    def __init__(self, config: Config):
        self.config = config
        self.source_dir = Path(config.get('remarkable.source_directory', ''))
        
        self.observer = None
        self.is_running = False
        self._sync_callback = None
        
        logger.info(f"SourceWatcher initialized for: {self.source_dir}")
    
    async def start(self, sync_callback: Optional[Callable] = None):
        """Start watching the source directory."""
        if not self.source_dir.exists():
            logger.error(f"Source directory does not exist: {self.source_dir}")
            return False
        
        self._sync_callback = sync_callback
        
        try:
            # Create event handler
            event_handler = SourceEventHandler(self)
            
            # Set up observer
            self.observer = Observer()
            self.observer.schedule(event_handler, str(self.source_dir), recursive=True)
            
            # Start observer
            self.observer.start()
            self.is_running = True
            
            logger.info(f"SourceWatcher started, monitoring: {self.source_dir}")
            
            # Initial sync no longer needed with event-driven sync system
            # await self.sync_manager.sync_if_needed(force=True)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start SourceWatcher: {e}")
            return False
    
    async def stop(self):
        """Stop watching the source directory."""
        if self.observer and self.is_running:
            self.observer.stop()
            self.observer.join()
            self.is_running = False
            logger.info("SourceWatcher stopped")
    
    async def on_source_change(self, event: FileSystemEvent):
        """Handle file changes in source directory."""
        logger.debug(f"Source change detected: {event.event_type} - {event.src_path}")
        
        # Filter out temporary files and directories we don't care about
        if self._should_ignore_file(event.src_path):
            return
        
        # Call sync callback if provided (processing happens directly from source)
        if self._sync_callback:
            try:
                await self._sync_callback(event)
            except Exception as e:
                logger.error(f"Error in sync callback: {e}")
    
    def _should_ignore_file(self, file_path: str) -> bool:
        """Check if file should be ignored based on patterns."""
        path = Path(file_path)
        
        # Ignore temporary files
        if path.name.startswith('.') or path.name.endswith('.tmp'):
            return True
        
        # Ignore non-reMarkable files
        relevant_extensions = {'.content', '.metadata', '.pagedata', '.rm', '.pdf', '.epub'}
        if path.suffix and path.suffix not in relevant_extensions:
            return True
        
        return False


class SourceEventHandler(FileSystemEventHandler):
    """File system event handler for source directory."""
    
    def __init__(self, source_watcher: SourceWatcher):
        self.source_watcher = source_watcher
        super().__init__()
    
    def on_any_event(self, event):
        """Handle any file system event."""
        if not event.is_directory:
            # Schedule async handling safely
            try:
                loop = asyncio.get_running_loop()
                # Create task in the existing event loop
                loop.create_task(self.source_watcher.on_source_change(event))
            except RuntimeError:
                # No event loop running - create a new one for this operation
                asyncio.run(self.source_watcher.on_source_change(event))


class ProcessingWatcher:
    """Watches the reMarkable source directory and triggers processing."""
    
    def __init__(self, config: Config):
        self.config = config
        self.source_dir = Path(config.get('remarkable.source_directory', ''))
        
        self.observer = None
        self.is_running = False
        self._processing_callback = None
        
        # Track recently processed files to avoid duplicate processing
        self._recently_processed: Dict[str, datetime] = {}
        self._processing_cooldown = timedelta(seconds=5)
        
        logger.info(f"ProcessingWatcher initialized for: {self.source_dir}")
    
    async def start(self, processing_callback: Optional[Callable] = None):
        """Start watching the source directory."""
        if not self.source_dir.exists():
            logger.warning(f"Source directory does not exist, creating: {self.source_dir}")
            self.source_dir.mkdir(parents=True, exist_ok=True)
        
        self._processing_callback = processing_callback
        
        try:
            # Create event handler
            event_handler = ProcessingEventHandler(self)
            
            # Set up observer
            self.observer = Observer()
            self.observer.schedule(event_handler, str(self.source_dir), recursive=True)
            
            # Start observer
            self.observer.start()
            self.is_running = True
            
            logger.info(f"ProcessingWatcher started, monitoring: {self.source_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start ProcessingWatcher: {e}")
            return False
    
    async def stop(self):
        """Stop watching the source directory."""
        if self.observer and self.is_running:
            self.observer.stop()
            self.observer.join()
            self.is_running = False
            logger.info("ProcessingWatcher stopped")
    
    async def on_local_change(self, event: FileSystemEvent):
        """Handle file changes in source directory."""
        file_path = event.src_path
        
        # Filter out files we don't want to process
        if self._should_ignore_file(file_path):
            return
        
        # Check cooldown to avoid duplicate processing
        now = datetime.now()
        if file_path in self._recently_processed:
            last_processed = self._recently_processed[file_path]
            if now - last_processed < self._processing_cooldown:
                logger.debug(f"Skipping recent file: {file_path}")
                return
        
        logger.info(f"Processing change: {event.event_type} - {Path(file_path).name}")
        
        # Update recent processing tracker
        self._recently_processed[file_path] = now
        
        # Clean up old entries
        cutoff = now - self._processing_cooldown * 10
        self._recently_processed = {
            path: time for path, time in self._recently_processed.items() 
            if time > cutoff
        }
        
        # Publish file event
        event_type_map = {
            'created': EventType.FILE_CREATED,
            'modified': EventType.FILE_MODIFIED,
            'deleted': EventType.FILE_DELETED
        }
        
        event_type = event_type_map.get(event.event_type, EventType.FILE_MODIFIED)
        publish_file_event(event_type, file_path)
        
        # Call processing callback if provided
        if self._processing_callback:
            try:
                await self._processing_callback(event)
            except Exception as e:
                logger.error(f"Error in processing callback: {e}")
    
    def _should_ignore_file(self, file_path: str) -> bool:
        """Check if file should be ignored for processing."""
        path = Path(file_path)
        
        # Ignore temporary files and hidden files
        if path.name.startswith('.') or path.name.endswith('.tmp'):
            return True
        
        # Only process reMarkable-specific files
        relevant_extensions = {'.content', '.metadata', '.rm'}
        if path.suffix and path.suffix not in relevant_extensions:
            return True
        
        return False


class ProcessingEventHandler(FileSystemEventHandler):
    """File system event handler for local processing directory."""
    
    def __init__(self, processing_watcher: ProcessingWatcher):
        self.processing_watcher = processing_watcher
        super().__init__()
    
    def on_any_event(self, event):
        """Handle any file system event."""
        if not event.is_directory:
            # Schedule async handling safely
            try:
                loop = asyncio.get_running_loop()
                # Create task in the existing event loop
                loop.create_task(self.processing_watcher.on_local_change(event))
            except RuntimeError:
                # No event loop running - create a new one for this operation  
                asyncio.run(self.processing_watcher.on_local_change(event))


class ReMarkableWatcher:
    """Main watcher that coordinates source watching and local processing."""

    def __init__(self, config: Config):
        self.config = config
        self._processing_locks = {}  # notebook_uuid -> timestamp to prevent duplicate processing
        
        # Initialize components
        self.source_watcher = SourceWatcher(config)
        self.processing_watcher = ProcessingWatcher(config)
        
        # Processing components (will be injected)
        self.text_extractor = None
        self.notion_sync_client = None
        self.todo_sync_client = None
        
        # Unified sync system
        self.unified_sync_manager = None
        
        self.is_running = False
        
        logger.info("ReMarkableWatcher initialized")
    
    async def on_file_change(self, event):
        """Unified handler for file changes - combines sync completion and processing."""
        logger.debug(f"🔄 File change detected: {event.src_path}")
        
        # Process the file immediately (unified single-watcher approach)
        await self.on_file_ready_for_processing(event)
    
    def set_text_extractor(self, text_extractor):
        """Set the text extractor for processing."""
        self.text_extractor = text_extractor
    
    def setup_unified_sync(self, db_manager):
        """Setup unified sync manager with configured integrations."""
        from ..integrations.readwise_sync import ReadwiseSyncTarget
        from ..integrations.notion_unified_sync import NotionSyncTarget
        from ..utils.api_keys import get_readwise_api_key, get_notion_api_key
        
        self.unified_sync_manager = UnifiedSyncManager(db_manager)
        
        # Setup Readwise integration if enabled and configured
        readwise_enabled = self.config.get('integrations.readwise.enabled', False)
        if readwise_enabled:
            readwise_api_key = get_readwise_api_key()
            if readwise_api_key:
                try:
                    readwise_target = ReadwiseSyncTarget(
                        access_token=readwise_api_key,
                        db_connection=db_manager.get_connection(),
                        author_name="reMarkable",
                        default_category="books"
                    )
                    self.unified_sync_manager.register_target(readwise_target)
                    logger.info("✅ Readwise sync target registered")
                except Exception as e:
                    logger.error(f"❌ Failed to setup Readwise sync: {e}")
            else:
                logger.warning("⚠️  Readwise enabled but no API key found")
        
        # Setup Notion integration with unified sync system
        notion_enabled = self.config.get('integrations.notion.enabled', False)
        if notion_enabled:
            notion_api_key = get_notion_api_key()
            notion_database_id = self.config.get('integrations.notion.database_id')
            tasks_database_id = self.config.get('integrations.notion.tasks_database_id')

            if notion_api_key and notion_database_id:
                try:
                    verify_ssl = self.config.get('integrations.notion.verify_ssl', False)
                    notion_target = NotionSyncTarget(
                        notion_token=notion_api_key,
                        database_id=notion_database_id,
                        tasks_database_id=tasks_database_id,  # Optional - for todo sync
                        db_manager=db_manager,
                        verify_ssl=verify_ssl
                    )
                    self.unified_sync_manager.register_target(notion_target)

                    if tasks_database_id:
                        logger.info("✅ Notion sync target registered (with todo support)")
                    else:
                        logger.info("✅ Notion sync target registered (notebooks only)")
                        logger.warning("⚠️  Todo sync disabled: tasks_database_id not configured")

                except Exception as e:
                    logger.error(f"❌ Failed to setup Notion sync: {e}")
            else:
                logger.warning("⚠️  Notion enabled but missing API key or database ID")
        
        logger.info(f"🔧 Unified sync manager setup complete. Registered targets: {list(self.unified_sync_manager.targets.keys())}")

    async def sync_pending_items(self, force_sync: bool = False):
        """Process all pending items that need syncing."""
        if not self.unified_sync_manager:
            logger.warning("Unified sync manager not available for startup sync")
            return

        try:
            # Get all items needing sync for all targets
            all_pending = []
            for target_name in self.unified_sync_manager.targets.keys():
                items = await self.unified_sync_manager.get_items_needing_sync(target_name, limit=50)
                all_pending.extend([(target_name, item) for item in items])

            if not all_pending:
                logger.info("📭 No pending items to sync")
                return

            # Safety check: If too many items need syncing, warn about potential duplicates
            if len(all_pending) > 10 and not force_sync:
                logger.warning(f"⚠️  Found {len(all_pending)} pending items to sync - this might create duplicates!")
                logger.warning("⚠️  This suggests sync tracking is incomplete. Consider:")
                logger.warning("   1. Running a migration to establish baseline sync state")
                logger.warning("   2. Use --force-startup-sync flag if you're sure this is safe")
                logger.warning("⏸️  Skipping startup sync for safety")
                return

            logger.info(f"📬 Found {len(all_pending)} pending items to sync")

            # Process each pending item
            success_count = 0
            for target_name, item in all_pending:
                item_type = item.get('item_type', 'unknown')
                name = item.get('notebook_name') or item.get('title', 'Unknown')
                logger.info(f"🔄 Syncing {name} ({item_type}) to {target_name}")

                try:
                    # Create SyncItem from the pending item data
                    from ..core.sync_engine import SyncItem, SyncItemType

                    # Map item_type string to SyncItemType enum
                    type_map = {
                        'notebook': SyncItemType.NOTEBOOK,
                        'todo': SyncItemType.TODO,
                        'highlight': SyncItemType.HIGHLIGHT
                    }

                    if item_type in type_map:
                        sync_item = SyncItem(
                            item_type=type_map[item_type],
                            item_id=item['item_id'],
                            content_hash='',  # Will be calculated
                            data=item,
                            source_table=item.get('source_table', 'unknown'),
                            created_at=datetime.now(),
                            updated_at=datetime.now()
                        )

                        result = await self.unified_sync_manager.sync_item_to_target(sync_item, target_name)

                        if result.success:
                            logger.info(f"✅ Successfully synced {name} to {target_name}")
                            success_count += 1
                        else:
                            logger.warning(f"⚠️ Failed to sync {name} to {target_name}: {result.error_message}")
                    else:
                        logger.warning(f"⚠️ Unknown item type: {item_type}")

                except Exception as e:
                    logger.error(f"❌ Error syncing {name}: {e}")

            logger.info(f"🎉 Startup sync completed: {success_count}/{len(all_pending)} items synced successfully")

        except Exception as e:
            logger.error(f"❌ Error during startup sync: {e}")

    async def _sync_notebook_unified(self, notebook_uuid: str, notebook_name: str, changed_pages: set = None) -> bool:
        """Sync notebook using the unified sync system."""
        logger.info(f"🔍 DEBUG: _sync_notebook_unified called with changed_pages = {changed_pages}")

        if not self.unified_sync_manager:
            logger.warning("Unified sync manager not available for notebook sync")
            return False
        
        logger.debug(f"Unified sync manager targets: {list(self.unified_sync_manager.targets.keys())}")
        if "notion" not in self.unified_sync_manager.targets:
            logger.warning("Notion target not registered in unified sync manager")
            return False
        
        try:
            # Get database connection
            from ..core.database import DatabaseManager
            db_path = self.config.get('database.path')
            db_manager = DatabaseManager(db_path)
            
            with db_manager.get_connection_context() as conn:
                # Fetch notebook data from database
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT
                        nte.notebook_uuid, nte.notebook_name, nte.page_number,
                        nte.text, nte.confidence, nte.page_uuid,
                        nm.full_path, nm.last_modified, nm.last_opened, nte.page_content_hash
                    FROM notebook_text_extractions nte
                    LEFT JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
                    WHERE nte.notebook_uuid = ?
                        AND nte.text IS NOT NULL
                        AND length(nte.text) > 0
                        AND nte.text NOT LIKE '%This appears to be a blank%'
                        AND nte.text NOT LIKE '%completely empty page%'
                    ORDER BY nte.page_number
                ''', (notebook_uuid,))

                rows = cursor.fetchall()
                if not rows:
                    logger.info(f"No text content found for notebook: {notebook_name}")
                    return False

                logger.debug(f"Found {len(rows)} text rows for notebook {notebook_name}")

                # DEBUGGING: Log what we fetched from database
                logger.info(f"🔍 DEBUG: Fetched {len(rows)} pages for notebook {notebook_uuid} ({notebook_name})")
                for i, row in enumerate(rows[:3]):  # Log first 3 pages
                    uuid, name, page_num, text, confidence, page_uuid, full_path, last_modified, last_opened, page_hash = row
                    logger.info(f"   Page {page_num}: {text[:50]}... (confidence: {confidence})")
                if len(rows) > 3:
                    logger.info(f"   ... and {len(rows) - 3} more pages")

                # Find pages that don't have sync records (need syncing)
                # Separate newly processed pages from backlog for prioritization
                newly_processed_pages = changed_pages if changed_pages else set()

                # Get all page numbers from DB with their content hashes
                all_page_numbers = {row[2] for row in rows}  # row[2] is page_number
                db_page_hashes = {}  # page_number -> content_hash from DB

                for row in rows:
                    uuid, name, page_num, text, confidence, page_uuid, full_path, last_modified, last_opened, page_content_hash = row
                    # Use the stored page_content_hash from database
                    if page_content_hash:
                        db_page_hashes[page_num] = page_content_hash
                    else:
                        # Fallback: calculate hash if not stored
                        import hashlib
                        content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
                        db_page_hashes[page_num] = content_hash

                # Check which pages have sync records and compare hashes
                cursor.execute('''
                    SELECT page_number, content_hash
                    FROM page_sync_records
                    WHERE notebook_uuid = ? AND target_name = 'notion'
                ''', (notebook_uuid,))

                sync_records = cursor.fetchall()
                synced_page_numbers = set()
                stale_pages = set()  # Pages with outdated content in Notion

                for page_num, sync_hash in sync_records:
                    synced_page_numbers.add(page_num)
                    # Check if content hash matches
                    if page_num in db_page_hashes and db_page_hashes[page_num] != sync_hash:
                        stale_pages.add(page_num)
                        logger.debug(f"  Page {page_num} has stale content (DB hash != sync hash)")

                # Pages without sync records need to be synced (backlog)
                missing_pages = all_page_numbers - synced_page_numbers - newly_processed_pages

                # Combine missing pages and stale pages into backlog
                backlog_pages = missing_pages.union(stale_pages)

                if backlog_pages:
                    if stale_pages:
                        logger.info(f"📝 Found {len(backlog_pages)} backlog pages (missing: {len(missing_pages)}, stale: {len(stale_pages)}): {sorted(list(backlog_pages))[:10]}{'...' if len(backlog_pages) > 10 else ''}")
                    else:
                        logger.info(f"📝 Found {len(backlog_pages)} backlog pages without sync records: {sorted(list(backlog_pages))[:10]}{'...' if len(backlog_pages) > 10 else ''}")

                if newly_processed_pages:
                    logger.info(f"🆕 Found {len(newly_processed_pages)} newly processed pages: {sorted(list(newly_processed_pages))}")

                # Combine: newly processed pages + backlog (will be prioritized in Notion sync)
                changed_pages = newly_processed_pages.union(backlog_pages)

                logger.info(f"🔄 Total pages to sync: {len(changed_pages)} (new: {len(newly_processed_pages)}, backlog: {len(backlog_pages)})")

                # Store metadata for prioritization in notebook_data
                sync_metadata = {
                    'newly_processed': list(newly_processed_pages),
                    'backlog': list(backlog_pages)
                }

                # Build notebook data structure
                pages = []
                metadata = {}

                for row in rows:
                    uuid, name, page_num, text, confidence, page_uuid, full_path, last_modified, last_opened, page_content_hash = row

                    # Add page data
                    pages.append({
                        'page_number': page_num,
                        'text': text,
                        'confidence': confidence or 0.0,
                        'page_uuid': page_uuid
                    })
                    
                    # Capture metadata from first row
                    if not metadata:
                        metadata = {
                            'full_path': full_path,
                            'last_modified': last_modified,
                            'last_opened': last_opened
                        }
                
                # Create SyncItem for notebook using same structure as unified sync
                from ..core.sync_engine import SyncItem, SyncItemType, SyncStatus

                # Convert pages to text_content for ContentFingerprint compatibility (same as unified sync)
                text_content = '\n'.join([
                    f"Page {page['page_number']}: {page['text']}"
                    for page in pages
                    if page.get('text', '').strip()
                ])

                notebook_data = {
                    'notebook_uuid': notebook_uuid,
                    'notebook_name': notebook_name,
                    'title': notebook_name,  # For compatibility with Notion sync
                    'pages': pages,
                    'text_content': text_content,  # For hash consistency
                    'page_count': len(pages),
                    'type': 'notebook',
                    'changed_pages': changed_pages,  # Additional info for incremental sync
                    'sync_metadata': sync_metadata,  # Priority info for rate limiting
                    'full_path': metadata.get('full_path'),
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                sync_item = SyncItem(
                    item_type=SyncItemType.NOTEBOOK,
                    item_id=notebook_uuid,
                    content_hash="",  # Will be calculated by target
                    data=notebook_data,
                    source_table="notebook_text_extractions",
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                
                # Sync to Notion via unified system
                result = await self.unified_sync_manager.sync_item_to_target(sync_item, "notion")

                # Handle different sync results properly
                if result.status == SyncStatus.SUCCESS:
                    logger.info(f"✅ Successfully synced notebook via unified sync: {notebook_name}")
                    return True
                elif result.status == SyncStatus.SKIPPED:
                    # SKIPPED is not necessarily an error - check the reason
                    skip_reason = result.metadata.get('reason', 'no reason provided') if result.metadata else 'no reason provided'

                    if skip_reason == 'already_synced':
                        logger.info(f"⏭️ Notebook already synced (up to date): {notebook_name}")
                        return True  # Already synced is a success
                    elif skip_reason == 'No pages to sync':
                        logger.warning(f"⚠️ Notebook has no pages to sync: {notebook_name}")
                        return False  # This is a real issue
                    else:
                        logger.warning(f"⏭️ Notebook sync skipped: {notebook_name} - {skip_reason}")
                        return False  # Other skip reasons treated as issues
                elif result.status == SyncStatus.FAILED:
                    error_msg = result.error_message if result.error_message else "No error details provided"
                    logger.error(f"❌ Failed to sync notebook via unified sync: {notebook_name}")
                    logger.error(f"   Error: {error_msg}")
                    logger.error(f"   Status: {result.status.value}")
                    if result.metadata:
                        logger.error(f"   Metadata: {result.metadata}")
                    return False
                else:
                    logger.error(f"❌ Unexpected sync result for notebook: {notebook_name}")
                    logger.error(f"   Status: {result.status.value}")
                    logger.error(f"   Error: {result.error_message or 'No error message'}")
                    logger.error(f"   Metadata: {result.metadata or 'No metadata'}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error syncing notebook {notebook_name} via unified sync: {e}")
            return False
    
    def set_notion_sync_client(self, notion_sync_client):
        """Set the Notion sync client for automatic updates."""
        self.notion_sync_client = notion_sync_client
    
    def set_todo_sync_client(self, todo_sync_client):
        """Set the todo sync client for automatic todo export."""
        self.todo_sync_client = todo_sync_client
    
    async def start(self):
        """Start the complete two-tier watching system."""
        try:
            logger.info("Starting ReMarkable two-tier watching system...")
            
            # Start source watcher (monitors reMarkable app directory)
            # Note: ProcessingWatcher disabled to avoid duplicate watching of same directory
            source_started = await self.source_watcher.start(self.on_file_change)
            
            if source_started:
                self.is_running = True
                logger.info(" Two-tier watching system started successfully")
                
                # Schedule delayed sync check
                asyncio.create_task(self._sync_maintenance_task())
                
                return True
            else:
                logger.error("L Failed to start one or both watchers")
                await self.stop()
                return False
                
        except Exception as e:
            logger.error(f"Failed to start ReMarkableWatcher: {e}")
            return False
    
    async def stop(self):
        """Stop the watching system."""
        if self.is_running:
            logger.info("Stopping ReMarkable watching system...")
            
            await self.source_watcher.stop()
            # ProcessingWatcher not used in unified approach
            
            self.is_running = False
            logger.info("ReMarkable watching system stopped")
    
    # LEGACY: This method was used when rsync was enabled - no longer needed
    # async def on_sync_completed(self, event):
    #     """Called when source directory sync is completed."""
    #     logger.info("📁 Sync completed, checking for changed notebooks...")
    #
    #     # Use metadata-driven processing to identify and process only changed notebooks
    #     await self._process_changed_notebooks_only()
    
    # LEGACY: This method was used for batch processing after rsync - no longer needed
    async def _process_changed_notebooks_only(self):
        """Process only notebooks that have changed according to metadata."""
        try:
            from ..core.notebook_paths import detect_metadata_changes, update_changed_metadata_only
            from ..core.database import DatabaseManager
            
            db_path = self.config.get('database.path')
            db_manager = DatabaseManager(db_path)
            
            with db_manager.get_connection_context() as conn:
                # Detect which notebooks have changed metadata
                source_dir = self.config.get('remarkable.source_directory')
                changed_uuids = detect_metadata_changes(source_dir, conn, "./data")
                
                if not changed_uuids:
                    logger.info("📊 No notebook changes detected - skipping processing")
                    return
                
                logger.info(f"📝 Processing {len(changed_uuids)} changed notebooks...")
                
                # Update changed metadata in database
                update_changed_metadata_only(source_dir, conn, changed_uuids, "./data")
                
                # Update Notion metadata for changed notebooks
                if self.unified_sync_manager:
                    # Use unified sync for metadata refresh
                    logger.info(f"🔄 Refreshing metadata for {len(changed_uuids)} changed notebooks: {list(changed_uuids)}")
                    notion_target = self.unified_sync_manager.get_target("notion")
                    if notion_target and hasattr(notion_target, 'refresh_metadata_for_notebooks'):
                        notion_target.refresh_metadata_for_notebooks(changed_uuids)
                    else:
                        logger.warning("⚠️ Notion target not available or doesn't support metadata refresh")
                elif self.notion_sync_client:
                    # Fallback to legacy notion client if unified sync not available
                    logger.info(f"🔄 Refreshing metadata via legacy client for {len(changed_uuids)} changed notebooks: {list(changed_uuids)}")
                    self.notion_sync_client.refresh_notion_metadata_for_specific_notebooks(conn, changed_uuids)
                else:
                    logger.warning("⚠️ Neither unified sync nor legacy notion client available - skipping targeted metadata refresh")
                
                # Process only the changed notebooks
                processed_count = 0
                for notebook_uuid in changed_uuids:
                    try:
                        # Get notebook name for exclusion check
                        notebook_name = None
                        if self.text_extractor and hasattr(self.text_extractor, '_should_exclude_notebook'):
                            cursor = conn.execute('SELECT visible_name FROM notebook_metadata WHERE notebook_uuid = ?', (notebook_uuid,))
                            name_result = cursor.fetchone()
                            notebook_name = name_result[0] if name_result else "Unknown"
                            
                            # Check if this notebook should be excluded
                            if self.text_extractor._should_exclude_notebook(notebook_uuid, notebook_name):
                                logger.info(f"⏭️ Skipping excluded notebook: {notebook_name}")
                                continue
                        
                        # Process this specific notebook
                        result = await self._process_notebook_async(notebook_uuid)
                        
                        if result.success:
                            logger.info(f"✅ Successfully processed: {result.notebook_name}")
                            processed_count += 1

                            # Refresh metadata for this specific notebook
                            if self.unified_sync_manager:
                                notion_target = self.unified_sync_manager.get_target("notion")
                                if notion_target and hasattr(notion_target, 'refresh_metadata_for_notebooks'):
                                    logger.info(f"🔄 Refreshing metadata for individual notebook: {result.notebook_name}")
                                    notion_target.refresh_metadata_for_notebooks({notebook_uuid})

                            # Trigger unified sync for all configured integrations (Notion, Readwise, etc.)
                            if self.unified_sync_manager:
                                # Use unified sync for notebook content
                                await self._sync_notebook_unified(notebook_uuid, result.notebook_name, result.processed_page_numbers)

                                # Sync any new todos from this notebook
                                await self._sync_notebook_todos_async(notebook_uuid, result.notebook_name)
                            else:
                                logger.warning(f"⚠️ Unified sync manager not available for {result.notebook_name}")
                        else:
                            logger.warning(f"⚠️ Failed to process {notebook_uuid}: {result.error_message}")
                            
                    except Exception as e:
                        logger.error(f"Error processing notebook {notebook_uuid}: {e}")
                
                logger.info(f"🎉 Completed processing {processed_count} changed notebooks")
                        
        except Exception as e:
            logger.error(f"Error in metadata-driven processing: {e}")
    
    async def on_file_ready_for_processing(self, event: FileSystemEvent):
        """Called when a file in source directory is ready for processing."""
        file_path = event.src_path

        # Extract UUID from file path and determine if it's a notebook, PDF, or EPUB
        try:
            path_obj = Path(file_path)
            if path_obj.suffix in {'.rm', '.content', '.metadata'}:
                file_uuid = path_obj.stem

                # Check document type and process accordingly
                is_notebook = await self._is_notebook_uuid(file_uuid)
                is_pdf_epub = await self._is_pdf_epub_uuid(file_uuid)

                # Process both types in parallel if both are true
                tasks = []

                if is_notebook:
                    logger.info(f"🔄 Detected handwritten notebook change: {file_uuid}")
                    tasks.append(self._process_notebook_async(file_uuid))

                if is_pdf_epub:
                    logger.info(f"📖 Detected PDF/EPUB highlight change: {file_uuid}")
                    tasks.append(self._process_highlights_async(file_uuid))

                if tasks:
                    # Run both processes in parallel
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Handle results
                    if is_notebook and len(results) >= 1:
                        result = results[0]
                        if isinstance(result, Exception):
                            logger.error(f"⚠️ Notebook processing failed: {result}")
                        elif result and result.success:
                            # Refresh metadata for this specific notebook
                            if self.unified_sync_manager:
                                notion_target = self.unified_sync_manager.get_target("notion")
                                if notion_target and hasattr(notion_target, 'refresh_metadata_for_notebooks'):
                                    logger.info(f"🔄 Refreshing metadata for immediate notebook change: {result.notebook_name}")
                                    notion_target.refresh_metadata_for_notebooks({file_uuid})

                                # Also sync content (including backlog pages) for this notebook
                                logger.info(f"🔄 Syncing content for immediate notebook change: {result.notebook_name}")
                                await self._sync_notebook_unified(file_uuid, result.notebook_name, result.processed_page_numbers)

                                # Sync any new todos from this notebook
                                await self._sync_notebook_todos_async(file_uuid, result.notebook_name)
                        else:
                            logger.warning(f"⚠️ Failed to process notebook change: {file_uuid}")

                    if is_pdf_epub:
                        highlight_result_idx = 1 if is_notebook else 0
                        if len(results) > highlight_result_idx:
                            highlight_result = results[highlight_result_idx]
                            if isinstance(highlight_result, Exception):
                                logger.error(f"⚠️ Highlight processing failed: {highlight_result}")
                else:
                    # This is a page file or other type - skip for now
                    logger.debug(f"⏩ Skipping non-document file: {file_uuid}")
            else:
                logger.debug(f"Ignoring non-document file: {file_path}")
        except Exception as e:
            logger.error(f"Error processing file change {file_path}: {e}")

    async def _is_notebook_uuid(self, uuid: str) -> bool:
        """Check if UUID corresponds to a handwritten notebook (not a page)."""
        try:
            from ..core.database import DatabaseManager
            db_path = self.config.get('database.path')
            db_manager = DatabaseManager(db_path)

            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM notebook_metadata WHERE notebook_uuid = ? LIMIT 1', (uuid,))
                return cursor.fetchone() is not None
        except Exception:
            return False

    async def _is_pdf_epub_uuid(self, uuid: str) -> bool:
        """Check if UUID corresponds to a PDF or EPUB document."""
        try:
            # Check if .content file exists and has fileType of 'pdf' or 'epub'
            source_dir = self.config.get('remarkable.source_directory')
            content_file = Path(source_dir) / f"{uuid}.content"

            if not content_file.exists():
                return False

            import json
            with open(content_file, 'r') as f:
                content_data = json.load(f)

            file_type = content_data.get('fileType', '')
            return file_type in ['pdf', 'epub']
        except Exception as e:
            logger.debug(f"Error checking if {uuid} is PDF/EPUB: {e}")
            return False

    async def _process_highlights_async(self, document_uuid: str):
        """Process PDF/EPUB highlights asynchronously."""
        import time
        from ..processors.enhanced_highlight_extractor_v3 import EnhancedHighlightExtractorV3
        from ..core.database import DatabaseManager

        try:
            logger.info(f"📖 Starting highlight extraction for {document_uuid}")

            # Get database connection
            db_path = self.config.get('database.path')
            db_manager = DatabaseManager(db_path)

            # Find the .content file
            source_dir = self.config.get('remarkable.source_directory')
            content_file = Path(source_dir) / f"{document_uuid}.content"

            if not content_file.exists():
                logger.warning(f"Content file not found: {content_file}")
                return {"success": False, "error": "Content file not found"}

            # Process highlights using v3 enhanced extractor
            loop = asyncio.get_event_loop()

            def extract_highlights():
                with db_manager.get_connection() as conn:
                    extractor = EnhancedHighlightExtractorV3(conn)
                    result = extractor.process_file(str(content_file))
                    return result

            result = await loop.run_in_executor(None, extract_highlights)

            if result.success:
                highlight_count = result.data.get('highlight_count', 0) if result.data else 0
                logger.info(f"✅ Extracted {highlight_count} highlights from {document_uuid}")

                # Sync to Readwise if enabled
                if self.unified_sync_manager and highlight_count > 0:
                    readwise_target = self.unified_sync_manager.get_target("readwise")
                    if readwise_target:
                        logger.info(f"📤 Syncing {highlight_count} highlights to Readwise...")
                        await self._sync_highlights_to_readwise(document_uuid, db_manager)
                    else:
                        logger.debug("Readwise sync not configured, skipping")

                return {"success": True, "highlight_count": highlight_count}
            else:
                logger.warning(f"⚠️ Highlight extraction failed: {result.error_message}")
                return {"success": False, "error": result.error_message}

        except Exception as e:
            logger.error(f"Error processing highlights for {document_uuid}: {e}")
            return {"success": False, "error": str(e)}

    async def _sync_highlights_to_readwise(self, document_uuid: str, db_manager):
        """Sync extracted highlights to Readwise using unified sync system."""
        from ..core.sync_engine import SyncItem, SyncItemType, ContentFingerprint

        try:
            # Get highlights from database
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, title, original_text, corrected_text, page_number, notebook_uuid, file_name
                    FROM enhanced_highlights
                    WHERE notebook_uuid = ?
                    ORDER BY page_number
                ''', (document_uuid,))

                highlights = cursor.fetchall()

            if not highlights:
                logger.debug(f"No highlights found for {document_uuid}")
                return

            # Create SyncItems for each highlight and use unified sync
            readwise_target = self.unified_sync_manager.get_target("readwise")
            if not readwise_target:
                logger.debug("Readwise sync not configured, skipping")
                return

            synced_count = 0
            skipped_count = 0

            for highlight_id, title, original_text, corrected_text, page_num, uuid, file_name in highlights:
                # Prepare highlight data
                highlight_data = {
                    'id': highlight_id,
                    'title': title,
                    'text': original_text,
                    'corrected_text': corrected_text,
                    'page_number': page_num,
                    'notebook_uuid': uuid,
                    'file_name': file_name,
                    'source_url': f'remarkable://{uuid}',
                    'location': int(page_num) if page_num and page_num.isdigit() else None,
                    'location_type': 'page'
                }

                # Generate content hash for deduplication
                content_hash = ContentFingerprint.for_highlight(highlight_data)

                # Create SyncItem
                sync_item = SyncItem(
                    item_type=SyncItemType.HIGHLIGHT,
                    item_id=f"{uuid}_{highlight_id}",
                    content_hash=content_hash,
                    data=highlight_data
                )

                # Use unified sync manager to sync (handles deduplication automatically)
                result = await self.unified_sync_manager.sync_item(sync_item, target_name="readwise")

                if result.status.name == 'SUCCESS':
                    synced_count += 1
                elif result.status.name == 'SKIPPED':
                    skipped_count += 1
                    logger.debug(f"Skipped highlight {highlight_id}: {result.metadata.get('reason', 'Unknown')}")

            logger.info(f"✅ Readwise sync complete: {synced_count} synced, {skipped_count} skipped (already synced)")

        except Exception as e:
            logger.error(f"Error syncing highlights to Readwise: {e}")

    async def _find_parent_notebook(self, page_uuid: str) -> Optional[str]:
        """Find the parent notebook UUID for a given page UUID."""
        try:
            from ..core.database import DatabaseManager
            db_path = self.config.get('database.path')
            db_manager = DatabaseManager(db_path)

            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT notebook_uuid FROM notebook_text_extractions WHERE page_uuid = ? LIMIT 1', (page_uuid,))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception:
            return None

    async def _process_notebook_async(self, notebook_uuid: str):
        """Process notebook asynchronously (wrapper for sync text extractor)."""
        # Check for recent processing to avoid duplicates
        import time
        current_time = time.time()

        logger.info(f"🔍 Processing check for {notebook_uuid}: locks={list(self._processing_locks.keys())}")

        if notebook_uuid in self._processing_locks:
            last_processed = self._processing_locks[notebook_uuid]
            time_since = current_time - last_processed
            logger.info(f"🔍 Last processed {time_since:.1f}s ago")
            if time_since < 5.0:  # 5 second cooldown
                logger.info(f"⏭️ Skipping duplicate processing for {notebook_uuid} (processed {time_since:.1f}s ago)")
                return NotebookProcessingResult(
                    success=False,
                    error_message="Skipped duplicate processing",
                    notebook_name="Unknown",
                    notebook_uuid=notebook_uuid,
                    processed_page_numbers=set(),
                    todos=[],
                    processing_time_ms=0
                )

        # Mark as being processed
        logger.info(f"🔍 Marking {notebook_uuid} as processing at {current_time}")
        self._processing_locks[notebook_uuid] = current_time

        # Run the synchronous text extraction in a thread pool with timeout
        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._process_notebook_sync,
                    notebook_uuid
                ),
                timeout=60.0  # 60 second timeout for processing
            )
        except asyncio.TimeoutError:
            logger.error(f"⏰ Processing timeout for {notebook_uuid} - skipping")
            return NotebookProcessingResult(
                success=False,
                error_message=f"Processing timeout after 60 seconds",
                notebook_name="Unknown",
                notebook_uuid=notebook_uuid,
                processed_page_numbers=[],
                todos=[],
                processing_time_ms=60000
            )

        # Handle case where text_extractor is not available
        if result is None:
            logger.warning(f"⚠️ No text extractor available for {notebook_uuid}")
            return NotebookProcessingResult(
                success=False,
                error_message="No text extractor available",
                notebook_name="Unknown",
                notebook_uuid=notebook_uuid,
                processed_page_numbers=[],
                todos=[],
                processing_time_ms=0
            )
        
        # If processing was successful, trigger unified sync
        if result and result.success and len(result.processed_page_numbers) > 0:
            logger.info(f"🔄 Processing successful, triggering unified sync for {notebook_uuid}")
            logger.info(f"🔍 DEBUG: Direct processing - result.processed_page_numbers = {result.processed_page_numbers}")
            await self._sync_notebook_unified(notebook_uuid, result.notebook_name, result.processed_page_numbers)

            # Also sync any new todos from this notebook (direct processing path)
            await self._sync_notebook_todos_async(notebook_uuid, result.notebook_name)
        elif result and result.success:
            logger.debug(f"📄 No pages processed for {notebook_uuid}, skipping sync")
        elif result:
            logger.warning(f"⚠️ Processing failed for {notebook_uuid}: {result.error_message}")
        
        return result
    
    def _process_notebook_sync(self, notebook_uuid: str):
        """Synchronous notebook processing."""
        if self.text_extractor:
            return self.text_extractor.process_notebook_incremental(notebook_uuid)
        return None

    async def _sync_notebook_todos_async(self, notebook_uuid: str, notebook_name: str):
        """Sync todos from a specific notebook that need syncing."""
        try:
            logger.info(f"🔍 DEBUG: _sync_notebook_todos_async called for {notebook_name}")
            logger.info(f"🔍 DEBUG: unified_sync_manager exists: {self.unified_sync_manager is not None}")
            if self.unified_sync_manager:
                logger.info(f"🔍 DEBUG: Available targets: {list(self.unified_sync_manager.targets.keys())}")
                logger.info(f"🔍 DEBUG: notion in targets: {'notion' in self.unified_sync_manager.targets}")

            if not self.unified_sync_manager or "notion" not in self.unified_sync_manager.targets:
                logger.warning(f"⏭️ Unified sync or Notion target not available - skipping todo sync for {notebook_name}")
                return

            from .sync_engine import SyncItem, SyncItemType
            from datetime import datetime

            logger.info(f"🔄 Checking for new todos in notebook: {notebook_name}")

            # Get todos needing sync
            todos_to_sync = await self.unified_sync_manager._get_todos_needing_sync("notion", limit=100)

            # Filter for todos from this specific notebook
            notebook_todos = [todo for todo in todos_to_sync
                            if todo['data'].get('notebook_uuid') == notebook_uuid]

            if notebook_todos:
                logger.info(f"📝 Found {len(notebook_todos)} new todos to sync from {notebook_name}")
                for todo_data in notebook_todos:
                    sync_item = SyncItem(
                        item_type=SyncItemType.TODO,
                        item_id=todo_data['item_id'],
                        content_hash=todo_data['content_hash'],
                        data=todo_data['data'],
                        source_table=todo_data['source_table'],
                        created_at=datetime.fromisoformat(todo_data['data']['created_at']) if todo_data['data'].get('created_at') else datetime.now(),
                        updated_at=datetime.fromisoformat(todo_data['updated_at']) if todo_data.get('updated_at') else datetime.now()
                    )

                    # Sync todo to Notion
                    result = await self.unified_sync_manager.sync_item_to_target(sync_item, "notion")
                    if result.status.value == 'success':
                        logger.info(f"✅ Successfully synced todo {todo_data['item_id']}: {todo_data['data']['text'][:50]}...")
                    else:
                        logger.warning(f"⚠️  Failed to sync todo {todo_data['item_id']}: {result.error_message}")
            else:
                logger.debug(f"📋 No new todos to sync from {notebook_name}")

        except Exception as e:
            logger.error(f"❌ Error syncing todos for notebook {notebook_name}: {e}")
            # Don't fail the entire processing pipeline for todo sync issues

    async def _sync_maintenance_task(self):
        """Background task to handle delayed syncs."""
        while self.is_running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                # Delayed sync no longer needed with event-driven sync system
                # await self.sync_manager.schedule_delayed_sync()
            except Exception as e:
                logger.error(f"Error in sync maintenance task: {e}")