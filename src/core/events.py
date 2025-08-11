"""
Event System for reMarkable Pipeline

This module provides a centralized event system for the pipeline, allowing
different components to communicate through events. It supports both synchronous
and asynchronous event handling.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
import json

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Enumeration of all event types in the system."""
    
    # File system events
    FILE_CREATED = "file_created"
    FILE_MODIFIED = "file_modified"
    FILE_DELETED = "file_deleted"
    SYNC_DETECTED = "sync_detected"
    
    # Processing events
    PROCESSING_STARTED = "processing_started"
    PROCESSING_COMPLETED = "processing_completed"
    PROCESSING_FAILED = "processing_failed"
    
    # Specific processor events
    OCR_COMPLETED = "ocr_completed"
    HIGHLIGHTS_EXTRACTED = "highlights_extracted"  # New event for highlight extraction
    TODOS_DETECTED = "todos_detected"
    
    # Integration events
    NOTION_SYNC_STARTED = "notion_sync_started"
    NOTION_SYNC_COMPLETED = "notion_sync_completed"
    NOTION_SYNC_FAILED = "notion_sync_failed"
    
    READWISE_SYNC_STARTED = "readwise_sync_started"
    READWISE_SYNC_COMPLETED = "readwise_sync_completed"
    READWISE_SYNC_FAILED = "readwise_sync_failed"
    
    MICROSOFT_TODO_SYNC_STARTED = "microsoft_todo_sync_started"
    MICROSOFT_TODO_SYNC_COMPLETED = "microsoft_todo_sync_completed"
    MICROSOFT_TODO_SYNC_FAILED = "microsoft_todo_sync_failed"
    
    # System events
    PIPELINE_STARTED = "pipeline_started"
    PIPELINE_STOPPED = "pipeline_stopped"
    ERROR_OCCURRED = "error_occurred"


@dataclass
class Event:
    """Represents an event in the system."""
    
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: Optional[str] = None
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            'event_type': self.event_type.value,
            'data': self.data,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
            'correlation_id': self.correlation_id
        }
    
    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class EventHandler:
    """Base class for event handlers."""
    
    def handle(self, event: Event) -> None:
        """Handle an event. Must be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement handle method")


class EventBus:
    """Central event bus for the pipeline."""
    
    def __init__(self):
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._event_history: List[Event] = []
        self._max_history_size = 1000
        
        logger.info("EventBus initialized")
    
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed handler {handler.__class__.__name__} to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                logger.debug(f"Unsubscribed handler {handler.__class__.__name__} from {event_type.value}")
            except ValueError:
                logger.warning(f"Handler {handler.__class__.__name__} was not subscribed to {event_type.value}")
    
    def publish(self, event: Event) -> None:
        """Publish an event to all subscribed handlers."""
        try:
            # Add to history
            self._add_to_history(event)
            
            # Get handlers for this event type
            handlers = self._handlers.get(event.event_type, [])
            
            logger.debug(f"Publishing event {event.event_type.value} to {len(handlers)} handlers")
            
            # Call all handlers
            for handler in handlers:
                try:
                    handler.handle(event)
                except Exception as e:
                    logger.error(f"Error in handler {handler.__class__.__name__} for event {event.event_type.value}: {e}")
            
        except Exception as e:
            logger.error(f"Error publishing event {event.event_type.value}: {e}")
    
    def publish_event(self, event_type: EventType, data: Dict[str, Any] = None, 
                     source: str = None, correlation_id: str = None) -> None:
        """Convenience method to publish an event."""
        event = Event(
            event_type=event_type,
            data=data or {},
            source=source,
            correlation_id=correlation_id
        )
        self.publish(event)
    
    def _add_to_history(self, event: Event) -> None:
        """Add event to history, maintaining size limit."""
        self._event_history.append(event)
        
        # Trim history if it gets too large
        if len(self._event_history) > self._max_history_size:
            self._event_history = self._event_history[-self._max_history_size:]
    
    def get_recent_events(self, event_type: EventType = None, limit: int = 50) -> List[Event]:
        """Get recent events, optionally filtered by type."""
        events = self._event_history
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        return events[-limit:] if limit else events
    
    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()
        logger.info("Event history cleared")


class LoggingEventHandler(EventHandler):
    """Event handler that logs events."""
    
    def __init__(self, log_level: int = logging.INFO):
        self.log_level = log_level
    
    def handle(self, event: Event) -> None:
        """Log the event."""
        message = f"Event: {event.event_type.value}"
        if event.source:
            message += f" from {event.source}"
        
        # Add key data to log message
        if event.data:
            key_items = []
            for key in ['file_path', 'highlight_count', 'todo_count', 'title', 'error_message']:
                if key in event.data:
                    key_items.append(f"{key}={event.data[key]}")
            
            if key_items:
                message += f" ({', '.join(key_items)})"
        
        logger.log(self.log_level, message)


class DatabaseEventHandler(EventHandler):
    """Event handler that stores events in the database."""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._initialize_table()
    
    def _initialize_table(self) -> None:
        """Create events table if it doesn't exist."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        data TEXT,
                        timestamp TEXT NOT NULL,
                        source TEXT,
                        correlation_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"Error creating events table: {e}")
    
    def handle(self, event: Event) -> None:
        """Store event in database."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO events (event_type, data, timestamp, source, correlation_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    event.event_type.value,
                    json.dumps(event.data) if event.data else None,
                    event.timestamp.isoformat(),
                    event.source,
                    event.correlation_id
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Error storing event in database: {e}")


class HighlightEventHandler(EventHandler):
    """Specialized handler for highlight extraction events."""
    
    def __init__(self, notification_callback: Optional[Callable] = None):
        self.notification_callback = notification_callback
    
    def handle(self, event: Event) -> None:
        """Handle highlight extraction events."""
        if event.event_type == EventType.HIGHLIGHTS_EXTRACTED:
            highlight_count = event.data.get('highlight_count', 0)
            title = event.data.get('title', 'Unknown')
            
            logger.info(f"✨ Extracted {highlight_count} highlights from '{title}'")
            
            # Call notification callback if provided
            if self.notification_callback:
                try:
                    self.notification_callback(event)
                except Exception as e:
                    logger.error(f"Error in highlight notification callback: {e}")


class IntegrationEventHandler(EventHandler):
    """Handler for integration-related events."""
    
    def __init__(self, integration_manager=None):
        self.integration_manager = integration_manager
    
    def handle(self, event: Event) -> None:
        """Handle integration events."""
        # Trigger relevant integrations based on processing events
        if event.event_type == EventType.HIGHLIGHTS_EXTRACTED:
            self._trigger_highlight_integrations(event)
        elif event.event_type == EventType.TODOS_DETECTED:
            self._trigger_todo_integrations(event)
        elif event.event_type == EventType.OCR_COMPLETED:
            self._trigger_text_integrations(event)
    
    def _trigger_highlight_integrations(self, event: Event) -> None:
        """Trigger integrations that handle highlights."""
        if not self.integration_manager:
            return
        
        try:
            # Trigger Readwise sync for highlights
            if hasattr(self.integration_manager, 'readwise') and self.integration_manager.readwise.is_enabled():
                logger.info("Triggering Readwise sync for new highlights")
                # Integration manager will handle the actual sync
                self.integration_manager.sync_highlights(event.data)
            
            # Trigger Notion sync for highlights
            if hasattr(self.integration_manager, 'notion') and self.integration_manager.notion.is_enabled():
                logger.info("Triggering Notion sync for new highlights")
                self.integration_manager.sync_highlights_to_notion(event.data)
                
        except Exception as e:
            logger.error(f"Error triggering highlight integrations: {e}")
    
    def _trigger_todo_integrations(self, event: Event) -> None:
        """Trigger integrations that handle todos."""
        if not self.integration_manager:
            return
        
        try:
            # Trigger Microsoft To Do sync
            if hasattr(self.integration_manager, 'microsoft_todo') and self.integration_manager.microsoft_todo.is_enabled():
                logger.info("Triggering Microsoft To Do sync for new todos")
                self.integration_manager.sync_todos(event.data)
                
        except Exception as e:
            logger.error(f"Error triggering todo integrations: {e}")
    
    def _trigger_text_integrations(self, event: Event) -> None:
        """Trigger integrations that handle transcribed text."""
        if not self.integration_manager:
            return
        
        try:
            # Trigger Notion sync for transcribed text
            if hasattr(self.integration_manager, 'notion') and self.integration_manager.notion.is_enabled():
                logger.info("Triggering Notion sync for transcribed text")
                self.integration_manager.sync_text_to_notion(event.data)
                
        except Exception as e:
            logger.error(f"Error triggering text integrations: {e}")


# Global event bus instance
_event_bus = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def setup_default_handlers(db_manager=None, integration_manager=None) -> EventBus:
    """Set up default event handlers."""
    event_bus = get_event_bus()
    
    # Add logging handler
    logging_handler = LoggingEventHandler()
    for event_type in EventType:
        event_bus.subscribe(event_type, logging_handler)
    
    # Add database handler if database manager is provided
    if db_manager:
        db_handler = DatabaseEventHandler(db_manager)
        for event_type in EventType:
            event_bus.subscribe(event_type, db_handler)
    
    # Add highlight handler
    highlight_handler = HighlightEventHandler()
    event_bus.subscribe(EventType.HIGHLIGHTS_EXTRACTED, highlight_handler)
    
    # Add integration handler if integration manager is provided
    if integration_manager:
        integration_handler = IntegrationEventHandler(integration_manager)
        event_bus.subscribe(EventType.HIGHLIGHTS_EXTRACTED, integration_handler)
        event_bus.subscribe(EventType.TODOS_DETECTED, integration_handler)
        event_bus.subscribe(EventType.OCR_COMPLETED, integration_handler)
    
    logger.info("Default event handlers configured")
    return event_bus


# Convenience functions for common event publishing
def publish_file_event(event_type: EventType, file_path: str, **kwargs):
    """Publish a file-related event."""
    event_bus = get_event_bus()
    data = {'file_path': file_path}
    data.update(kwargs)
    event_bus.publish_event(event_type, data, source='file_watcher')


def publish_processing_event(event_type: EventType, processor_type: str, file_path: str, **kwargs):
    """Publish a processing-related event."""
    event_bus = get_event_bus()
    data = {
        'processor_type': processor_type,
        'file_path': file_path
    }
    data.update(kwargs)
    event_bus.publish_event(event_type, data, source=processor_type)


def publish_integration_event(event_type: EventType, integration_name: str, **kwargs):
    """Publish an integration-related event."""
    event_bus = get_event_bus()
    data = {'integration': integration_name}
    data.update(kwargs)
    event_bus.publish_event(event_type, data, source=integration_name)


def publish_highlight_event(file_path: str, highlight_count: int, title: str, **kwargs):
    """Convenience function to publish highlight extraction event."""
    event_bus = get_event_bus()
    data = {
        'file_path': file_path,
        'highlight_count': highlight_count,
        'title': title
    }
    data.update(kwargs)
    event_bus.publish_event(EventType.HIGHLIGHTS_EXTRACTED, data, source='highlight_extractor')


if __name__ == "__main__":
    # Example usage
    import time
    
    # Set up event bus with logging
    event_bus = setup_default_handlers()
    
    # Publish some example events
    publish_file_event(EventType.FILE_CREATED, "/path/to/notebook.content")
    
    publish_highlight_event(
        file_path="/path/to/document.content",
        highlight_count=5,
        title="My Document"
    )
    
    publish_processing_event(
        EventType.PROCESSING_COMPLETED,
        processor_type="highlight_extractor",
        file_path="/path/to/document.content",
        success=True
    )
    
    # Show recent events
    recent_events = event_bus.get_recent_events(limit=10)
    print(f"\nRecent events ({len(recent_events)}):")
    for event in recent_events:
        print(f"  {event.timestamp.strftime('%H:%M:%S')} - {event.event_type.value}")
    
    print("\nEvent system demonstration complete!")