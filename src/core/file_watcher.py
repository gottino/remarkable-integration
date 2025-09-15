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
            if notion_api_key and notion_database_id:
                try:
                    verify_ssl = self.config.get('integrations.notion.verify_ssl', False)
                    notion_target = NotionSyncTarget(
                        notion_token=notion_api_key,
                        database_id=notion_database_id,
                        db_connection=db_manager.get_connection(),
                        verify_ssl=verify_ssl
                    )
                    self.unified_sync_manager.register_target(notion_target)
                    logger.info("✅ Notion sync target registered")
                except Exception as e:
                    logger.error(f"❌ Failed to setup Notion sync: {e}")
            else:
                logger.warning("⚠️  Notion enabled but missing API key or database ID")
        
        logger.info(f"🔧 Unified sync manager setup complete. Registered targets: {list(self.unified_sync_manager.targets.keys())}")
    
    async def _sync_notebook_unified(self, notebook_uuid: str, notebook_name: str) -> bool:
        """Sync notebook using the unified sync system."""
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
                        nm.full_path, nm.last_modified, nm.last_opened
                    FROM notebook_text_extractions nte
                    LEFT JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
                    WHERE nte.notebook_uuid = ? 
                        AND nte.text IS NOT NULL AND length(nte.text) > 0
                    ORDER BY nte.page_number
                ''', (notebook_uuid,))
                
                rows = cursor.fetchall()
                if not rows:
                    logger.info(f"No text content found for notebook: {notebook_name}")
                    return False
                
                logger.debug(f"Found {len(rows)} text rows for notebook {notebook_name}")
                
                # Build notebook data structure
                pages = []
                metadata = {}
                
                for row in rows:
                    uuid, name, page_num, text, confidence, page_uuid, full_path, last_modified, last_opened = row
                    
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
                
                # Create SyncItem for notebook
                from ..core.sync_engine import SyncItem, SyncItemType
                
                notebook_data = {
                    'title': notebook_name,
                    'notebook_name': notebook_name,
                    'notebook_uuid': notebook_uuid,
                    'pages': pages,
                    **metadata
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
                success = result.success
                
                if success:
                    logger.info(f"✅ Successfully synced notebook via unified sync: {notebook_name}")
                    return True
                else:
                    error_msg = result.error_message if hasattr(result, 'error_message') and result.error_message else "Unknown error"
                    logger.error(f"❌ Failed to sync notebook via unified sync: {notebook_name} - {error_msg}")
                    logger.error(f"   Sync result status: {result.status if hasattr(result, 'status') else 'Unknown'}")
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
    
    async def on_sync_completed(self, event):
        """Called when source directory sync is completed."""
        logger.info("📁 Sync completed, checking for changed notebooks...")
        
        # Use metadata-driven processing to identify and process only changed notebooks
        await self._process_changed_notebooks_only()
    
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
                # Note: With unified sync, metadata updates happen automatically during sync
                if not self.unified_sync_manager and self.notion_sync_client:
                    # Legacy metadata refresh only if unified sync not available
                    self.notion_sync_client.refresh_notion_metadata_for_specific_notebooks(conn, changed_uuids)
                
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
                            
                            # Trigger unified sync for all configured integrations (Notion, Readwise, etc.)
                            if self.unified_sync_manager:
                                # Use unified sync for both Notion and other integrations
                                await self._sync_notebook_unified(notebook_uuid, result.notebook_name)
                                await self._sync_to_unified_targets_async(notebook_uuid, result)
                            else:
                                # Fallback to legacy Notion sync if unified sync not available
                                if self.notion_sync_client:
                                    changed_pages = result.processed_page_numbers if hasattr(result, 'processed_page_numbers') else None
                                    await self._sync_notebook_to_notion_async(notebook_uuid, result.notebook_name, changed_pages)
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
        
        # Extract notebook UUID from file path
        try:
            path_obj = Path(file_path)
            if path_obj.suffix in {'.rm', '.content', '.metadata'}:
                notebook_uuid = path_obj.stem
                logger.info(f"🔄 Processing notebook change: {notebook_uuid}")
                
                # Process the notebook immediately 
                if self.text_extractor:
                    await self._process_notebook_async(notebook_uuid)
                else:
                    logger.warning("No text extractor available for processing")
            else:
                logger.debug(f"Ignoring non-notebook file: {file_path}")
        except Exception as e:
            logger.error(f"Error processing file change {file_path}: {e}")
    
    async def _process_notebook_async(self, notebook_uuid: str):
        """Process notebook asynchronously (wrapper for sync text extractor)."""
        # Run the synchronous text extraction in a thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, 
            self._process_notebook_sync,
            notebook_uuid
        )
        
        # If processing was successful, trigger unified sync
        if result and result.success and len(result.processed_page_numbers) > 0:
            logger.info(f"🔄 Processing successful, triggering unified sync for {notebook_uuid}")
            await self._sync_notebook_unified(notebook_uuid, result.notebook_name)
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
    
    async def _sync_notebook_to_notion_async(self, notebook_uuid: str, notebook_name: str, changed_pages: set = None):
        """Sync a single notebook to Notion after processing."""
        try:
            logger.info(f"📄 Syncing notebook to Notion: {notebook_name}")
            
            # Get database connection from config
            from ..core.database import DatabaseManager
            from ..integrations.notion_incremental import NotionSyncTracker
            db_path = self.config.get('database.path')
            db_manager = DatabaseManager(db_path)
            
            with db_manager.get_connection_context() as conn:
                # Use incremental change detection to determine what actually needs syncing
                sync_tracker = NotionSyncTracker(db_manager)
                changes = sync_tracker.get_notebook_changes(notebook_uuid)
                
                # Fetch the specific notebook (skip metadata refresh since we did it at startup)
                notebooks = self.notion_sync_client.fetch_notebooks_from_db(conn, refresh_changed_metadata=False)
                target_notebook = next((nb for nb in notebooks if nb.uuid == notebook_uuid), None)
                
                if target_notebook:
                    existing_page_id = self.notion_sync_client.find_existing_page(notebook_uuid)
                    
                    if existing_page_id:
                        # Check for content changes with better filtering
                        if changes['new_pages'] or changes['changed_pages']:
                            # Log what we're syncing
                            total_to_sync = len(changes['new_pages']) + len(changes['changed_pages'])
                            logger.info(f"📝 Syncing {total_to_sync} pages to Notion: {notebook_name} ({len(changes['new_pages'])} new, {len(changes['changed_pages'])} changed)")
                            
                            # Sync both new and changed pages incrementally  
                            all_changed_pages = set(changes['new_pages'] + changes['changed_pages'])
                            self.notion_sync_client.update_existing_page(existing_page_id, target_notebook, all_changed_pages)
                            
                            # Mark individual pages as synced
                            for page_num in all_changed_pages:
                                page = next((p for p in target_notebook.pages if p.page_number == page_num), None)
                                if page:
                                    page_content_hash = sync_tracker._calculate_page_content_hash((None, None, None, page.confidence, page.page_number, page.text))
                                    sync_tracker.mark_page_synced(notebook_uuid, page_num, page.page_uuid, page_content_hash)
                        elif changes['metadata_changed']:
                            # Only metadata changed - update metadata
                            logger.info(f"📄 Updating metadata only for: {notebook_name}")
                            properties = {
                                "Total Pages": {"number": target_notebook.total_pages},
                                "Last Updated": {"date": {"start": datetime.now().isoformat()}}
                            }
                            self.notion_sync_client.client.pages.update(page_id=existing_page_id, properties=properties)
                        else:
                            logger.info(f"⏭️ No changes detected for: {notebook_name}")
                            return
                            
                        # Mark as synced after successful content or metadata sync
                        sync_tracker.mark_notebook_synced(
                            notebook_uuid, existing_page_id,
                            changes['current_content_hash'],
                            changes['current_metadata_hash'], 
                            changes['current_total_pages']
                        )
                        page_id = existing_page_id
                    else:
                        # New notebook - create page
                        logger.info(f"📖 Creating new Notion page for: {notebook_name}")
                        page_id = self.notion_sync_client.create_notebook_page(target_notebook)
                        
                        # Mark as synced for new notebooks
                        sync_tracker.mark_notebook_synced(
                            notebook_uuid, page_id,
                            changes['current_content_hash'],
                            changes['current_metadata_hash'], 
                            changes['current_total_pages']
                        )
                    logger.info(f"✅ Synced notebook to Notion: {notebook_name} (page: {page_id})")
                    
                    # After successful notebook sync, sync any new todos
                    if self.todo_sync_client:
                        try:
                            stats = self.todo_sync_client.sync_todos(days_back=30, dry_run=False)
                            if stats['exported'] > 0:
                                logger.info(f"📋 Exported {stats['exported']} new todos to Tasks database")
                            elif stats['total'] > 0:
                                logger.debug(f"📋 {stats['total']} todos found but {stats['errors']} failed to export")
                        except Exception as e:
                            logger.warning(f"⚠️ Todo sync failed: {e}")
                    
                else:
                    logger.warning(f"⚠️ Notebook not found for Notion sync: {notebook_name}")
                    
        except Exception as e:
            logger.error(f"❌ Failed to sync notebook to Notion: {notebook_name} - {e}")
            # Don't fail the entire processing pipeline for Notion sync issues
    
    async def _sync_to_unified_targets_async(self, notebook_uuid: str, processing_result):
        """Sync processed notebook data to unified targets (Readwise, etc.)."""
        try:
            from .sync_engine import SyncItem, SyncItemType
            from datetime import datetime
            import hashlib
            
            logger.info(f"🔄 Syncing notebook to unified targets: {processing_result.notebook_name}")
            
            # Sync enhanced highlights if any were extracted
            if hasattr(processing_result, 'extracted_highlights'):
                highlights = processing_result.extracted_highlights
                for highlight in highlights:
                    # Create sync item for each highlight
                    highlight_data = {
                        'text': highlight.get('original_text', ''),
                        'corrected_text': highlight.get('corrected_text', ''),
                        'title': processing_result.notebook_name,
                        'page_number': highlight.get('page_number'),
                        'confidence': highlight.get('confidence'),
                        'notebook_uuid': notebook_uuid,
                        'match_score': highlight.get('match_score')
                    }
                    
                    # Create content hash for deduplication
                    content_hash = hashlib.sha256(
                        f"{notebook_uuid}:{highlight.get('corrected_text', highlight.get('original_text', ''))}:{highlight.get('page_number', '')}".encode()
                    ).hexdigest()
                    
                    sync_item = SyncItem(
                        item_type=SyncItemType.HIGHLIGHT,
                        item_id=f"{notebook_uuid}_{highlight.get('page_number', 'unknown')}_{len(highlight_data['text'])}",
                        content_hash=content_hash,
                        data=highlight_data,
                        source_table='enhanced_highlights',
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    
                    # Sync to all targets
                    results = await self.unified_sync_manager.sync_item_to_all_targets(sync_item)
                    
                    # Log results
                    for target_name, result in results.items():
                        if result.success:
                            logger.info(f"✅ Highlight synced to {target_name}")
                        else:
                            logger.warning(f"⚠️  Failed to sync highlight to {target_name}: {result.error_message}")
            
            logger.info(f"🎉 Unified sync completed for notebook: {processing_result.notebook_name}")
            
        except Exception as e:
            logger.error(f"❌ Error syncing notebook {notebook_uuid} to unified targets: {e}")
            # Don't fail the entire processing pipeline for unified sync issues
    
    async def _sync_maintenance_task(self):
        """Background task to handle delayed syncs."""
        while self.is_running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                # Delayed sync no longer needed with event-driven sync system
                # await self.sync_manager.schedule_delayed_sync()
            except Exception as e:
                logger.error(f"Error in sync maintenance task: {e}")