#!/usr/bin/env python3
"""
Example script showing how to integrate the highlight extractor
into the main pipeline and use it with the existing codebase.

This demonstrates:
1. Setting up the highlight extractor as part of the pipeline
2. Processing files and extracting highlights
3. Using the event system to handle results
4. Exporting results to CSV (backward compatibility)
"""

import os
import sys
import logging
from pathlib import Path

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.highlight_extractor import HighlightExtractor, process_directory
from src.core.database import DatabaseManager
from src.core.events import setup_default_handlers, EventType
from src.core.file_watcher import FileWatcher
from src.utils.config import Config


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HighlightPipelineDemo:
    """Demonstration of the highlight extraction pipeline."""
    
    def __init__(self, config_path: str = None):
        """Initialize the demo pipeline."""
        # Load configuration
        self.config = Config(config_path) if config_path else Config()
        
        # Initialize database
        db_path = self.config.get('database.path', 'remarkable_pipeline.db')
        self.db_manager = DatabaseManager(db_path)
        
        # Set up event system
        self.event_bus = setup_default_handlers(self.db_manager)
        
        # Initialize highlight extractor
        self.highlight_extractor = HighlightExtractor(self.db_manager)
        
        # Set up file watcher if sync directory is configured
        sync_dir = self.config.get('remarkable.sync_directory')
        if sync_dir and os.path.exists(sync_dir):
            self.file_watcher = FileWatcher(sync_dir)
            self._setup_file_watcher()
        else:
            logger.warning("No sync directory configured or directory doesn't exist")
            self.file_watcher = None
        
        logger.info("Highlight pipeline demo initialized")
    
    def _setup_file_watcher(self):
        """Set up file watcher to process .content files automatically."""
        def on_file_event(file_path: str, event_type: str):
            """Handle file events from the watcher."""
            if file_path.endswith('.content'):
                logger.info(f"Content file {event_type}: {file_path}")
                
                if event_type in ['created', 'modified']:
                    if self.highlight_extractor.can_process(file_path):
                        logger.info(f"Processing highlights for {file_path}")
                        result = self.highlight_extractor.process_file(file_path)
                        
                        if result.success:
                            highlight_count = len(result.data.get('highlights', []))
                            logger.info(f"✅ Extracted {highlight_count} highlights")
                        else:
                            logger.error(f"❌ Failed to process: {result.error_message}")
        
        # Register callback
        self.file_watcher.add_callback(on_file_event)
    
    def process_existing_files(self, directory: str) -> None:
        """Process all existing .content files in a directory."""
        logger.info(f"Processing existing files in: {directory}")
        
        results = process_directory(directory, self.db_manager)
        
        total_highlights = sum(results.values())
        successful_files = len([count for count in results.values() if count > 0])
        
        logger.info(f"📊 Processing Summary:")
        logger.info(f"  Files processed: {len(results)}")
        logger.info(f"  Files with highlights: {successful_files}")
        logger.info(f"  Total highlights extracted: {total_highlights}")
        
        # Show individual results
        for file_path, count in results.items():
            file_name = os.path.basename(file_path)
            status = "✅" if count > 0 else "⚪"
            logger.info(f"  {status} {file_name}: {count} highlights")
    
    def export_all_highlights(self, output_path: str) -> None:
        """Export all highlights to CSV."""
        logger.info(f"Exporting all highlights to: {output_path}")
        
        try:
            self.highlight_extractor.export_highlights_to_csv(output_path)
            logger.info("✅ Export completed successfully")
        except Exception as e:
            logger.error(f"❌ Export failed: {e}")
    
    def show_highlights_for_document(self, title: str) -> None:
        """Display highlights for a specific document."""
        highlights = self.highlight_extractor.get_highlights_for_document(title)
        
        if not highlights:
            logger.info(f"No highlights found for '{title}'")
            return
        
        logger.info(f"📚 Highlights for '{title}' ({len(highlights)} total):")
        
        current_page = None
        for highlight in highlights:
            page = highlight['page_number']
            if page != current_page:
                logger.info(f"\n  📄 Page {page}:")
                current_page = page
            
            confidence = highlight.get('confidence', 1.0)
            confidence_icon = "🔥" if confidence > 0.9 else "⭐" if confidence > 0.7 else "⚡"
            
            text = highlight['text']
            # Truncate long highlights for display
            if len(text) > 100:
                text = text[:97] + "..."
            
            logger.info(f"    {confidence_icon} {text}")
    
    def start_watching(self) -> None:
        """Start watching for file changes."""
        if not self.file_watcher:
            logger.error("File watcher not initialized - check sync directory configuration")
            return
        
        logger.info("🔍 Starting file watcher...")
        logger.info("Press Ctrl+C to stop")
        
        try:
            self.file_watcher.start()
        except KeyboardInterrupt:
            logger.info("Stopping file watcher...")
            self.file_watcher.stop()
    
    def run_interactive_demo(self) -> None:
        """Run an interactive demonstration."""
        logger.info("🚀 Starting Highlight Extraction Demo")
        
        while True:
            print("\n" + "="*60)
            print("reMarkable Highlight Extractor Demo")
            print("="*60)
            print("1. Process directory")
            print("2. Export highlights to CSV") 
            print("3. Show highlights for document")
            print("4. Start file watcher")
            print("5. Show recent events")
            print("6. Exit")
            print("="*60)
            
            choice = input("Select option (1-6): ").strip()
            
            try:
                if choice == "1":
                    directory = input("Enter directory path: ").strip()
                    if os.path.exists(directory):
                        self.process_existing_files(directory)
                    else:
                        logger.error("Directory does not exist")
                
                elif choice == "2":
                    output_path = input("Enter output CSV path (or press Enter for 'highlights.csv'): ").strip()
                    if not output_path:
                        output_path = "highlights.csv"
                    self.export_all_highlights(output_path)
                
                elif choice == "3":
                    title = input("Enter document title: ").strip()
                    if title:
                        self.show_highlights_for_document(title)
                    else:
                        logger.info("Please enter a document title")
                
                elif choice == "4":
                    self.start_watching()
                
                elif choice == "5":
                    events = self.event_bus.get_recent_events(limit=10)
                    logger.info(f"📋 Recent Events ({len(events)}):")
                    for event in events[-10:]:  # Show last 10
                        timestamp = event.timestamp.strftime('%H:%M:%S')
                        logger.info(f"  {timestamp} - {event.event_type.value}")
                        if event.data:
                            key_info = []
                            for key in ['file_path', 'highlight_count', 'title']:
                                if key in event.data:
                                    value = event.data[key]
                                    if key == 'file_path':
                                        value = os.path.basename(value)
                                    key_info.append(f"{key}={value}")
                            if key_info:
                                logger.info(f"    ({', '.join(key_info)})")
                
                elif choice == "6":
                    logger.info("👋 Goodbye!")
                    break
                
                else:
                    print("Invalid choice. Please select 1-6.")
                    
            except Exception as e:
                logger.error(f"Error: {e}")
                
            input("\nPress Enter to continue...")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="reMarkable Highlight Extractor Demo")
    parser.add_argument(
        "--config", 
        help="Path to configuration file"
    )
    parser.add_argument(
        "--directory", 
        help="Process all files in this directory and exit"
    )
    parser.add_argument(
        "--export",
        help="Export highlights to this CSV file"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Start file watcher (requires sync directory in config)"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run interactive demo (default if no other options)"
    )
    
    args = parser.parse_args()
    
    # Initialize demo
    demo = HighlightPipelineDemo(args.config)
    
    # Run based on arguments
    if args.directory:
        demo.process_existing_files(args.directory)
        
        if args.export:
            demo.export_all_highlights(args.export)
    
    elif args.watch:
        demo.start_watching()
    
    elif args.export:
        demo.export_all_highlights(args.export)
    
    else:
        # Default to interactive mode
        demo.run_interactive_demo()


if __name__ == "__main__":
    main()
