"""
File Watching System for reMarkable Integration

Implements a two-tier watching system:
1. SourceWatcher - Monitors the original reMarkable app directory
2. ProcessingWatcher - Monitors the local sync directory for processing

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
from ..utils.config import Config

logger = logging.getLogger(__name__)


@dataclass
class SyncEvent:
    """Represents a sync operation that needs to be performed."""
    source_path: str
    target_path: str
    event_type: str  # 'created', 'modified', 'deleted'
    timestamp: datetime
    

class SyncManager:
    """Manages rsync operations between source and target directories."""
    
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
    
    def __init__(self, config: Config, sync_manager: SyncManager):
        self.config = config
        self.sync_manager = sync_manager
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
            
            # Perform initial sync
            await self.sync_manager.sync_if_needed(force=True)
            
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
        
        # Trigger sync
        await self.sync_manager.sync_if_needed()
        
        # Call sync callback if provided
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
    """Watches the local sync directory and triggers processing."""
    
    def __init__(self, config: Config):
        self.config = config
        self.local_dir = Path(config.get('remarkable.local_sync_directory', './data/remarkable_sync'))
        
        self.observer = None
        self.is_running = False
        self._processing_callback = None
        
        # Track recently processed files to avoid duplicate processing
        self._recently_processed: Dict[str, datetime] = {}
        self._processing_cooldown = timedelta(seconds=5)
        
        logger.info(f"ProcessingWatcher initialized for: {self.local_dir}")
    
    async def start(self, processing_callback: Optional[Callable] = None):
        """Start watching the local sync directory."""
        if not self.local_dir.exists():
            logger.warning(f"Local sync directory does not exist, creating: {self.local_dir}")
            self.local_dir.mkdir(parents=True, exist_ok=True)
        
        self._processing_callback = processing_callback
        
        try:
            # Create event handler
            event_handler = ProcessingEventHandler(self)
            
            # Set up observer
            self.observer = Observer()
            self.observer.schedule(event_handler, str(self.local_dir), recursive=True)
            
            # Start observer
            self.observer.start()
            self.is_running = True
            
            logger.info(f"ProcessingWatcher started, monitoring: {self.local_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start ProcessingWatcher: {e}")
            return False
    
    async def stop(self):
        """Stop watching the local sync directory."""
        if self.observer and self.is_running:
            self.observer.stop()
            self.observer.join()
            self.is_running = False
            logger.info("ProcessingWatcher stopped")
    
    async def on_local_change(self, event: FileSystemEvent):
        """Handle file changes in local sync directory."""
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
        self.sync_manager = SyncManager(config)
        self.source_watcher = SourceWatcher(config, self.sync_manager)
        self.processing_watcher = ProcessingWatcher(config)
        
        # Processing components (will be injected)
        self.text_extractor = None
        
        self.is_running = False
        
        logger.info("ReMarkableWatcher initialized")
    
    def set_text_extractor(self, text_extractor):
        """Set the text extractor for processing."""
        self.text_extractor = text_extractor
    
    async def start(self):
        """Start the complete two-tier watching system."""
        try:
            logger.info("Starting ReMarkable two-tier watching system...")
            
            # Start source watcher (monitors reMarkable app directory)
            source_started = await self.source_watcher.start(self.on_sync_completed)
            
            # Start processing watcher (monitors local sync directory)
            processing_started = await self.processing_watcher.start(self.on_file_ready_for_processing)
            
            if source_started and processing_started:
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
            await self.processing_watcher.stop()
            
            self.is_running = False
            logger.info("ReMarkable watching system stopped")
    
    async def on_sync_completed(self, event):
        """Called when source directory sync is completed."""
        logger.debug("Sync completed, local processing will be triggered automatically")
    
    async def on_file_ready_for_processing(self, event: FileSystemEvent):
        """Called when a file in local sync directory is ready for processing."""
        if not self.text_extractor:
            logger.warning("No text extractor configured, skipping processing")
            return
        
        file_path = event.src_path
        
        try:
            # Check if this is a notebook content file
            if file_path.endswith('.content'):
                logger.info(f"Processing notebook: {Path(file_path).name}")
                
                # Extract notebook UUID from filename
                notebook_uuid = Path(file_path).stem
                
                # Process with incremental updates
                result = await self._process_notebook_async(notebook_uuid)
                
                if result.success:
                    logger.info(f" Successfully processed notebook: {result.notebook_name}")
                else:
                    logger.error(f"L Failed to process notebook: {result.error_message}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
    
    async def _process_notebook_async(self, notebook_uuid: str):
        """Process notebook asynchronously (wrapper for sync text extractor)."""
        # Run the synchronous text extraction in a thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            self._process_notebook_sync,
            notebook_uuid
        )
    
    def _process_notebook_sync(self, notebook_uuid: str):
        """Synchronous notebook processing."""
        if self.text_extractor:
            return self.text_extractor.process_notebook_incremental(notebook_uuid)
        return None
    
    async def _sync_maintenance_task(self):
        """Background task to handle delayed syncs."""
        while self.is_running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                await self.sync_manager.schedule_delayed_sync()
            except Exception as e:
                logger.error(f"Error in sync maintenance task: {e}")