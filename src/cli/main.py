#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Command-line interface for reMarkable Integration.

Provides commands for processing reMarkable files, extracting highlights,
managing configuration, and running the integration pipeline.
"""

import os
import sys
import logging
import time
import shutil
import yaml
from pathlib import Path
from typing import Optional

import click

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import Config
from src.utils.api_keys import get_api_key_manager
from src.core.database import DatabaseManager
from src.core.events import setup_default_handlers, get_event_bus, EventType
from src.processors.highlight_extractor import HighlightExtractor, process_directory
from src.processors.enhanced_highlight_extractor import (
    EnhancedHighlightExtractor, 
    process_directory_enhanced,
    compare_extraction_methods
)
from src.processors.ocr_engine import OCREngine, process_directory_with_ocr
from src.processors.pdf_ocr_engine import PDFOCREngine, process_directory_with_pdf_ocr
from src.processors.notebook_text_extractor import (
    NotebookTextExtractor,
    extract_text_from_directory,
    analyze_remarkable_library
)


# Configure logging
def setup_logging(config: Config):
    """Setup logging based on configuration."""
    level = getattr(logging, config.get('logging.level', 'INFO').upper())
    format_str = config.get('logging.format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    log_file = config.get('logging.file')
    
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(format_str))
    handlers.append(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(format_str))
        handlers.append(file_handler)
    
    logging.basicConfig(level=level, handlers=handlers, force=True)


@click.group()
@click.option('--config', '-c', help='Path to configuration file')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, config: Optional[str], verbose: bool):
    """reMarkable Integration CLI - Extract and sync content from reMarkable tablets."""
    
    # Initialize configuration
    ctx.ensure_object(dict)
    ctx.obj['config'] = Config(config)
    
    # Override log level if verbose
    if verbose:
        ctx.obj['config'].set('logging.level', 'DEBUG')
    
    # Setup logging
    setup_logging(ctx.obj['config'])
    
    # Validate configuration
    issues = ctx.obj['config'].validate()
    if issues:
        click.echo("Configuration issues found:", err=True)
        for issue in issues:
            click.echo(f"  - {issue}", err=True)
        
        # Don't exit for some commands that don't require full config
        if ctx.invoked_subcommand not in ['config', 'init', 'version']:
            click.echo("\nRun 'remarkable-integration config check' for details.", err=True)
            sys.exit(1)


@cli.group()
@click.pass_context
def config(ctx):
    """Configuration management commands."""
    pass


@config.command('init')
@click.option('--output', '-o', default='config.yaml', help='Output configuration file path')
@click.option('--sync-dir', help='reMarkable sync directory path')
def config_init(output: str, sync_dir: Optional[str]):
    """Initialize configuration file with example settings."""
    
    config_obj = Config()
    
    # Set sync directory if provided
    if sync_dir:
        if not os.path.exists(sync_dir):
            click.echo(f"Warning: Sync directory does not exist: {sync_dir}", err=True)
        config_obj.set('remarkable.sync_directory', sync_dir)
    
    try:
        config_obj.create_example_config(output)
        click.echo(f"Configuration template created: {output}")
        click.echo("\nNext steps:")
        click.echo(f"1. Edit {output} with your settings")
        click.echo("2. Set your reMarkable sync directory")
        click.echo("3. Run 'remarkable-integration config check' to validate")
        
    except Exception as e:
        click.echo(f"Failed to create configuration: {e}", err=True)
        sys.exit(1)


@config.command('check')
@click.pass_context
def config_check(ctx):
    """Check configuration for issues."""
    
    config_obj = ctx.obj['config']
    issues = config_obj.validate()
    
    if not issues:
        click.echo("Configuration is valid")
        
        # Show key settings
        click.echo("\nKey settings:")
        click.echo(f"  Sync directory: {config_obj.get('remarkable.sync_directory')}")
        click.echo(f"  Database path: {config_obj.get('database.path')}")
        click.echo(f"  Log level: {config_obj.get('logging.level')}")
        
        # Check enabled integrations
        integrations = []
        if config_obj.is_enabled('integrations.notion'):
            integrations.append('Notion')
        if config_obj.is_enabled('integrations.readwise'):
            integrations.append('Readwise')
        if config_obj.is_enabled('integrations.microsoft_todo'):
            integrations.append('Microsoft To Do')
        
        if integrations:
            click.echo(f"  Enabled integrations: {', '.join(integrations)}")
        else:
            click.echo("  Enabled integrations: None")
    else:
        click.echo("Configuration issues found:", err=True)
        for issue in issues:
            click.echo(f"  - {issue}", err=True)
        sys.exit(1)


@config.command('show')
@click.option('--section', help='Show only specific configuration section')
@click.pass_context
def config_show(ctx, section: Optional[str]):
    """Show current configuration."""
    
    config_obj = ctx.obj['config']
    
    if section:
        data = config_obj.get_section(section)
        if data:
            click.echo(f"Configuration section '{section}':")
            _print_config_section(data)
        else:
            click.echo(f"Configuration section '{section}' not found", err=True)
            sys.exit(1)
    else:
        click.echo(f"Configuration loaded from: {config_obj.config_path or 'defaults'}")
        click.echo("\nFull configuration:")
        _print_config_section(config_obj.config_data)


@config.group('api-key')
def api_key():
    """API key management commands."""
    pass


@api_key.command('set')
@click.option('--method', type=click.Choice(['auto', 'keychain', 'encrypted']), 
              default='auto', help='Storage method (default: auto)')
@click.option('--key', help='API key (will prompt securely if not provided)')
def api_key_set(method: str, key: Optional[str]):
    """Set Anthropic API key for AI-powered OCR."""
    
    api_manager = get_api_key_manager()
    
    if not key:
        import getpass
        click.echo("🔑 Setting up Anthropic API key for AI-powered OCR")
        click.echo("Get your API key from: https://console.anthropic.com/")
        click.echo()
        
        try:
            key = getpass.getpass("Enter your API key (input hidden): ").strip()
        except KeyboardInterrupt:
            click.echo("\nCancelled.")
            sys.exit(0)
        
        if not key:
            click.echo("No API key provided.", err=True)
            sys.exit(1)
    
    # Basic validation
    if not key.startswith('sk-ant-'):
        click.echo("⚠️  Warning: Anthropic API keys usually start with 'sk-ant-'")
        if not click.confirm("Continue anyway?"):
            sys.exit(0)
    
    # Store the key
    if api_manager.store_anthropic_api_key(key, method):
        click.echo(f"✅ API key stored successfully using {method} method")
        click.echo("You can now use AI-powered OCR commands!")
    else:
        click.echo("❌ Failed to store API key", err=True)
        sys.exit(1)


@api_key.command('get')
def api_key_get():
    """Check if Anthropic API key is available."""
    
    api_manager = get_api_key_manager()
    api_key = api_manager.get_anthropic_api_key()
    
    if api_key:
        click.echo(f"✅ API key found: {api_key[:12]}...")
        
        # Show storage location
        keys = api_manager.list_stored_keys()
        if 'anthropic' in keys:
            location = keys['anthropic']
            click.echo(f"📍 Storage location: {location}")
    else:
        click.echo("❌ No API key found")
        click.echo("Use 'config api-key set' to configure your API key")


@api_key.command('remove')
@click.confirmation_option(prompt='Are you sure you want to remove the stored API key?')
def api_key_remove():
    """Remove stored Anthropic API key."""
    
    api_manager = get_api_key_manager()
    
    if api_manager.remove_anthropic_api_key():
        click.echo("✅ API key removed successfully")
    else:
        click.echo("ℹ️  No API key was stored")


@api_key.command('list')
def api_key_list():
    """List all stored API keys and their locations."""
    
    api_manager = get_api_key_manager()
    keys = api_manager.list_stored_keys()
    
    if keys:
        click.echo("📋 Stored API keys:")
        for service, location in keys.items():
            click.echo(f"  🔑 {service}: {location}")
    else:
        click.echo("ℹ️  No API keys stored")
        click.echo("Use 'config api-key set' to add an API key")


def _print_config_section(data, indent=0):
    """Print configuration section with proper formatting."""
    for key, value in data.items():
        if isinstance(value, dict):
            click.echo("  " * indent + f"{key}:")
            _print_config_section(value, indent + 1)
        else:
            click.echo("  " * indent + f"{key}: {value}")


@cli.group()
@click.pass_context
def database(ctx):
    """Database management commands."""
    pass


@database.command('stats')
@click.option('--database', help='Database path (overrides config)')
@click.pass_context
def database_stats(ctx, database: Optional[str]):
    """Show database statistics."""
    
    config_obj = ctx.obj['config']
    db_path = database or config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        stats = db_manager.get_database_stats()
        
        click.echo(f"Database: {stats['database_path']}")
        click.echo(f"Size: {stats['database_size_mb']:.2f} MB")
        click.echo(f"Recent events (24h): {stats['recent_events_24h']}")
        click.echo("\nTable counts:")
        
        for table, count in stats['tables'].items():
            click.echo(f"  {table}: {count}")
            
    except Exception as e:
        click.echo(f"Failed to get database stats: {e}", err=True)
        sys.exit(1)


@database.command('backup')
@click.option('--output', '-o', help='Backup file path (optional)')
@click.option('--database', help='Database path (overrides config)')
@click.pass_context
def database_backup(ctx, output: Optional[str], database: Optional[str]):
    """Create database backup."""
    
    config_obj = ctx.obj['config']
    db_path = database or config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        backup_path = db_manager.create_backup_manually(output)
        click.echo(f"Database backup created: {backup_path}")
        
    except Exception as e:
        click.echo(f"Failed to create backup: {e}", err=True)
        sys.exit(1)


@database.command('cleanup')
@click.option('--days', default=30, help='Keep data from last N days (default: 30)')
@click.option('--vacuum', is_flag=True, help='Vacuum database after cleanup')
@click.option('--database', help='Database path (overrides config)')
@click.pass_context
def database_cleanup(ctx, days: int, vacuum: bool, database: Optional[str]):
    """Clean up old data from database."""
    
    config_obj = ctx.obj['config']
    db_path = database or config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        click.echo(f"Cleaning up data older than {days} days...")
        db_manager.cleanup_old_data(days)
        
        if vacuum:
            click.echo("Vacuuming database...")
            db_manager.vacuum()
        
        click.echo("Database cleanup completed")
        
    except Exception as e:
        click.echo(f"Database cleanup failed: {e}", err=True)
        sys.exit(1)


@database.command('init')
@click.option('--production', is_flag=True, help='Create production database')
@click.option('--db-path', help='Database path (overrides default naming)')
@click.pass_context
def database_init(ctx, production: bool, db_path: Optional[str]):
    """Initialize a new database (development or production)."""
    
    config_obj = ctx.obj['config']
    
    # Determine database path
    if db_path:
        target_path = db_path
    elif production:
        target_path = "production_remarkable.db"
    else:
        target_path = config_obj.get('database.path', 'remarkable_pipeline.db')
    
    # Check if database already exists
    if os.path.exists(target_path):
        env_type = "production" if production else "development"
        if not click.confirm(f"Database already exists at {target_path}. Overwrite?"):
            click.echo("Database initialization cancelled")
            sys.exit(0)
        
        # Create backup of existing database
        backup_path = f"{target_path}.backup"
        shutil.copy2(target_path, backup_path)
        click.echo(f"Existing database backed up to {backup_path}")
    
    try:
        # Initialize new database
        db_manager = DatabaseManager(target_path)
        
        env_type = "production" if production else "development"
        click.echo(f"✅ {env_type.title()} database initialized: {target_path}")
        
        # Show stats
        stats = db_manager.get_database_stats()
        click.echo(f"Database size: {stats['database_size_mb']:.2f} MB")
        click.echo(f"Tables: {len(stats['tables'])}")
        
        if production:
            click.echo("\n💡 Production database ready for use!")
            click.echo(f"   Use --database {target_path} with other commands")
            click.echo(f"   Or update your config: database.path: {target_path}")
        
    except Exception as e:
        click.echo(f"Failed to initialize database: {e}", err=True)
        sys.exit(1)


@database.command('switch')
@click.option('--to', 'target_env', type=click.Choice(['development', 'production']), 
              help='Switch to environment (development or production)')
@click.option('--path', help='Switch to specific database path')
@click.pass_context
def database_switch(ctx, target_env: Optional[str], path: Optional[str]):
    """Switch default database environment."""
    
    config_obj = ctx.obj['config']
    current_path = config_obj.get('database.path')
    
    if path:
        new_path = path
    elif target_env == 'production':
        new_path = "production_remarkable.db"
    elif target_env == 'development':
        new_path = "remarkable_pipeline.db"
    else:
        click.echo("Must specify --to environment or --path", err=True)
        sys.exit(1)
    
    if not os.path.exists(new_path):
        click.echo(f"Database not found: {new_path}", err=True)
        click.echo(f"Use 'database init' to create it first")
        sys.exit(1)
    
    try:
        # Update configuration 
        config_obj.set('database.path', new_path)
        
        # Save to config file if it exists
        if config_obj.config_path:
            with open(config_obj.config_path, 'r') as f:
                config_data = yaml.safe_load(f) or {}
            
            # Update the database path
            if 'database' not in config_data:
                config_data['database'] = {}
            config_data['database']['path'] = new_path
            
            with open(config_obj.config_path, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, indent=2)
        
        env_name = target_env or "custom"
        click.echo(f"✅ Switched to {env_name} database: {new_path}")
        
        # Show stats for the new database
        db_manager = DatabaseManager(new_path)
        stats = db_manager.get_database_stats()
        click.echo(f"Database size: {stats['database_size_mb']:.2f} MB")
        click.echo(f"Recent events (24h): {stats['recent_events_24h']}")
        
    except Exception as e:
        click.echo(f"Failed to switch database: {e}", err=True)
        sys.exit(1)


@database.command('list-environments')
@click.pass_context
def database_list_environments(ctx):
    """List available database environments."""
    
    config_obj = ctx.obj['config']
    current_path = config_obj.get('database.path')
    
    click.echo("Available database environments:")
    
    # Standard database files
    databases = [
        ('development', 'remarkable_pipeline.db'),
        ('production', 'production_remarkable.db'),
    ]
    
    # Add current path if it's different
    if current_path not in [db[1] for db in databases]:
        databases.append(('current', current_path))
    
    for env_name, db_path in databases:
        if os.path.exists(db_path):
            try:
                db_manager = DatabaseManager(db_path)
                stats = db_manager.get_database_stats()
                size_mb = stats['database_size_mb']
                tables = len(stats['tables'])
                recent_events = stats['recent_events_24h']
                
                status = "✅"
                marker = " (current)" if db_path == current_path else ""
                
                click.echo(f"  {status} {env_name}{marker}: {db_path}")
                click.echo(f"      Size: {size_mb:.2f} MB, Tables: {tables}, Recent events: {recent_events}")
                
            except Exception as e:
                click.echo(f"  ❌ {env_name}: {db_path} (error: {e})")
        else:
            click.echo(f"  ⚪ {env_name}: {db_path} (not found)")
    
    click.echo(f"\nCurrent default: {current_path}")


@database.command('recent-activity')
@click.option('--database', help='Database path (overrides config)')
@click.option('--limit', default=10, help='Number of recent events to show (default: 10)')
@click.pass_context
def database_recent_activity(ctx, database: Optional[str], limit: int):
    """Show recent database activity."""
    
    config_obj = ctx.obj['config']
    db_path = database or config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get recent processing results
            cursor.execute('''
                SELECT pr.created_at, pr.processor_type, pr.success, pr.error_message,
                       pr.processing_time_ms, f.file_path
                FROM processing_results pr
                JOIN files f ON pr.file_id = f.id
                ORDER BY pr.created_at DESC
                LIMIT ?
            ''', (limit,))
            
            results = cursor.fetchall()
            
            if results:
                click.echo(f"Recent processing activity ({len(results)} events):")
                click.echo()
                
                for created_at, processor_type, success, error_msg, time_ms, file_path in results:
                    status = "✅" if success else "❌"
                    file_name = os.path.basename(file_path) if file_path else "Unknown"
                    time_str = f"{time_ms}ms" if time_ms else "N/A"
                    
                    click.echo(f"{status} {created_at} - {processor_type}")
                    click.echo(f"   File: {file_name} ({time_str})")
                    if not success and error_msg:
                        click.echo(f"   Error: {error_msg}")
                    click.echo()
            else:
                click.echo("No recent processing activity found")
        
    except Exception as e:
        click.echo(f"Failed to get recent activity: {e}", err=True)
        sys.exit(1)


@cli.group()
@click.pass_context
def process(ctx):
    """File processing commands."""
    pass


@process.command('directory')
@click.argument('directory')
@click.option('--enhanced', is_flag=True, help='Use enhanced extraction with EPUB matching')
@click.option('--export', help='Export results to CSV file')
@click.option('--compare', is_flag=True, help='Compare basic vs enhanced extraction')
@click.option('--text-extraction', is_flag=True, help='Extract text from notebooks using OCR')
@click.pass_context
def process_directory(ctx, directory: str, enhanced: bool, export: Optional[str], compare: bool, text_extraction: bool):
    """Process all files in a directory."""
    
    if not os.path.exists(directory):
        click.echo(f"Directory not found: {directory}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        if compare:
            click.echo("Comparing extraction methods...")
            results = compare_extraction_methods(directory)
            _display_comparison_results(results)
        elif text_extraction:
            click.echo("Extracting text from notebooks using OCR...")
            db_path = config_obj.get('database.path')
            language = config_obj.get('ocr.language', 'en')
            confidence = config_obj.get('ocr.confidence_threshold', 0.7)
            
            results = extract_text_from_directory(
                directory, 
                db_path=db_path,
                language=language,
                confidence_threshold=confidence
            )
            _display_text_extraction_results(results)
        elif enhanced:
            click.echo("Processing with enhanced extraction...")
            results = process_directory_enhanced(directory, db_manager)
            _display_processing_results(results, "enhanced passages")
        else:
            click.echo("Processing with basic extraction...")
            results = process_directory(directory, db_manager)
            _display_processing_results(results, "highlights")
        
        # Export if requested
        if export and not compare:
            click.echo(f"\nExporting results to {export}...")
            with db_manager.get_connection() as conn:
                if enhanced:
                    extractor = EnhancedHighlightExtractor(conn)
                    extractor.export_enhanced_highlights_to_csv(export)
                else:
                    extractor = HighlightExtractor(conn)
                    extractor.export_highlights_to_csv(export)
            click.echo("Export completed")
            
    except Exception as e:
        click.echo(f"Processing failed: {e}", err=True)
        logging.exception("Processing error")
        sys.exit(1)


def _display_processing_results(results: dict, item_type: str):
    """Display processing results."""
    total_items = sum(results.values())
    processed_files = len([count for count in results.values() if count > 0])
    
    click.echo(f"\nProcessing Results:")
    click.echo(f"  Files processed: {len(results)}")
    click.echo(f"  Files with {item_type}: {processed_files}")
    click.echo(f"  Total {item_type}: {total_items}")
    
    if total_items > 0:
        click.echo(f"\nResults by file:")
        for file_path, count in results.items():
            if count > 0:
                file_name = os.path.basename(file_path)
                click.echo(f"  {file_name}: {count} {item_type}")


def _display_text_extraction_results(results: dict):
    """Display text extraction results."""
    successful = len([r for r in results.values() if r.success])
    total_regions = sum(r.total_text_regions for r in results.values())
    
    click.echo(f"\nText Extraction Results:")
    click.echo(f"  Total notebooks: {len(results)}")
    click.echo(f"  Successfully processed: {successful}")
    click.echo(f"  Total text regions: {total_regions}")
    
    success_rate = (successful / len(results)) * 100 if results else 0
    click.echo(f"  Success rate: {success_rate:.1f}%")
    
    if successful > 0:
        click.echo(f"\nResults by notebook:")
        for result in results.values():
            if result.success:
                click.echo(f"  {result.notebook_name}: {result.total_text_regions} text regions")


def _display_comparison_results(results: dict):
    """Display comparison results."""
    click.echo("\nComparison Results:")
    
    if 'error' not in results.get('basic_method', {}):
        basic_count = results['basic_method']['highlight_count']
        basic_time = results['timing']['basic_method']
        click.echo(f"  Basic method: {basic_count} highlights in {basic_time:.2f}s")
    else:
        click.echo(f"  Basic method: Error - {results['basic_method'].get('error', 'Unknown')}")
    
    if 'error' not in results.get('enhanced_method', {}):
        enhanced_count = results['enhanced_method']['highlight_count']
        enhanced_time = results['timing']['enhanced_method']
        click.echo(f"  Enhanced method: {enhanced_count} passages in {enhanced_time:.2f}s")
        
        if 'error' not in results.get('basic_method', {}):
            basic_count = results['basic_method']['highlight_count']
            if basic_count > 0:
                ratio = enhanced_count / basic_count
                reduction = basic_count - enhanced_count
                click.echo(f"  Compression ratio: {ratio:.2f} ({reduction} fragments merged)")
    else:
        click.echo(f"  Enhanced method: Error - {results['enhanced_method'].get('error', 'Unknown')}")


@process.command('file')
@click.argument('file_path')
@click.option('--enhanced', is_flag=True, help='Use enhanced extraction')
@click.option('--show', is_flag=True, help='Display extracted content')
@click.pass_context
def process_file(ctx, file_path: str, enhanced: bool, show: bool):
    """Process a single file."""
    
    if not os.path.exists(file_path):
        click.echo(f"File not found: {file_path}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection() as conn:
            if enhanced:
                extractor = EnhancedHighlightExtractor(conn)
                click.echo("Processing with enhanced extraction...")
            else:
                extractor = HighlightExtractor(conn)
                click.echo("Processing with basic extraction...")
            
            if not extractor.can_process(file_path):
                click.echo(f"Cannot process file: {file_path}", err=True)
                click.echo("File must be a .content file with PDF/EPUB type")
                sys.exit(1)
            
            result = extractor.process_file(file_path)
            
            if result.success:
                highlights = result.data.get('highlights', [])
                item_type = "passages" if enhanced else "highlights"
                click.echo(f"Extracted {len(highlights)} {item_type}")
                
                if show and highlights:
                    click.echo(f"\nExtracted content:")
                    for i, highlight in enumerate(highlights, 1):
                        text = highlight.get('corrected_text', highlight.get('text', ''))
                        page = highlight.get('page_number', 'Unknown')
                        click.echo(f"\n{i}. Page {page}:")
                        click.echo(f"   {text}")
            else:
                click.echo(f"Processing failed: {result.error_message}", err=True)
                sys.exit(1)
                
    except Exception as e:
        click.echo(f"Processing failed: {e}", err=True)
        logging.exception("File processing error")
        sys.exit(1)


@cli.group()
@click.pass_context
def ocr(ctx):
    """OCR processing commands for handwritten text.
    
    Supports both reMarkable files (.rm) and PDF files.
    For PDF processing: Requires EasyOCR and pdf2image
    For .rm processing: Requires EasyOCR, cairosvg and system Cairo library
    """
    pass


@ocr.command('directory')
@click.argument('directory')
@click.option('--language', default='en', help='OCR language (default: en)')
@click.option('--confidence', default=0.7, type=float, help='Minimum confidence threshold (default: 0.7)')
@click.option('--export', help='Export OCR results to CSV file')
@click.pass_context
def ocr_directory(ctx, directory: str, language: str, confidence: float, export: Optional[str]):
    """Process directory with OCR for handwritten text recognition."""
    
    if not os.path.exists(directory):
        click.echo(f"Directory not found: {directory}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        # Check if OCR is available
        with db_manager.get_connection() as conn:
            ocr_engine = OCREngine(conn, language=language, confidence_threshold=confidence)
            if not ocr_engine.is_available():
                click.echo("OCR engine not available. Please install EasyOCR and cairosvg:", err=True)
                click.echo("  poetry add easyocr cairosvg", err=True)
                sys.exit(1)
        
        click.echo(f"Processing directory with OCR (language: {language}, confidence: {confidence})...")
        results = process_directory_with_ocr(
            directory, 
            db_manager, 
            language=language, 
            confidence_threshold=confidence
        )
        
        total_regions = sum(results.values())
        processed_files = len([count for count in results.values() if count > 0])
        
        click.echo(f"\nOCR Processing Results:")
        click.echo(f"  Files processed: {len(results)}")
        click.echo(f"  Files with text: {processed_files}")
        click.echo(f"  Total text regions: {total_regions}")
        
        if total_regions > 0:
            click.echo(f"\nResults by file:")
            for file_path, count in results.items():
                if count > 0:
                    file_name = os.path.basename(file_path)
                    click.echo(f"  {file_name}: {count} text regions")
        
        # Export if requested
        if export:
            click.echo(f"\nExporting OCR results to {export}...")
            with db_manager.get_connection() as conn:
                ocr_engine = OCREngine(conn)
                ocr_engine.export_ocr_results_to_csv(export)
            click.echo("Export completed")
            
    except Exception as e:
        click.echo(f"OCR processing failed: {e}", err=True)
        logging.exception("OCR processing error")
        sys.exit(1)


# Text Extraction Commands
@cli.group()
def text():
    """Text extraction commands."""
    pass


@text.command('extract')
@click.argument('directory')
@click.option('--output-dir', help='Directory to save individual text files')
@click.option('--language', default='en', help='OCR language (default: en)')
@click.option('--confidence', default=0.7, type=float, help='Minimum confidence threshold (default: 0.7)')
@click.option('--format', 'output_format', type=click.Choice(['txt', 'md', 'json', 'csv']), default='md', help='Output format (default: md for Markdown)')
@click.option('--include-pdf-epub', is_flag=True, help='Include notebooks with associated PDF/EPUB files (default: skip them)')
@click.option('--max-pages', type=int, help='Maximum pages to process per notebook (for testing)')
@click.option('--notebook-list', type=click.Path(exists=True), help='File containing notebook UUIDs or names to process (one per line)')
@click.option('--skip-metadata-update', is_flag=True, help='Skip automatic metadata update (faster but may use stale data)')
@click.pass_context
def extract_text(ctx, directory: str, output_dir: Optional[str], language: str, confidence: float, output_format: str, include_pdf_epub: bool, max_pages: Optional[int], notebook_list: Optional[str], skip_metadata_update: bool):
    """Extract text from notebooks using OCR."""
    
    if not os.path.exists(directory):
        click.echo(f"Directory not found: {directory}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        click.echo("🚀 Extracting text from notebooks...")
        click.echo(f"📂 Input: {directory}")
        if output_dir:
            click.echo(f"📁 Output: {output_dir}")
        click.echo(f"🌐 Language: {language}")
        click.echo(f"📊 Confidence: {confidence}")
        click.echo()
        
        # Auto-update metadata (unless skipped)
        if not skip_metadata_update:
            click.echo("📊 Updating notebook metadata...")
            
            # Try to find reMarkable sync directory for metadata
            metadata_dir = _find_remarkable_sync_directory(config_obj, directory)
            
            if metadata_dir:
                try:
                    from ..core.notebook_paths import update_notebook_metadata
                    from ..core.database import DatabaseManager
                    
                    # Get data directory from config
                    data_dir = config_obj.get('remarkable.data_directory', './data')
                    
                    db_manager = DatabaseManager(db_path)
                    with db_manager.get_connection() as conn:
                        updated_count = update_notebook_metadata(metadata_dir, conn, data_dir)
                    
                    click.echo(f"✅ Updated {updated_count} notebook metadata records")
                except Exception as e:
                    click.echo(f"⚠️  Warning: Could not update metadata: {e}")
                    click.echo("   Continuing with existing metadata...")
            else:
                click.echo("⚠️  Warning: Could not find reMarkable sync directory")
                click.echo("   Use 'update-paths' command manually if needed")
            
            click.echo()
        
        results = extract_text_from_directory(
            directory,
            output_dir=output_dir,
            db_path=db_path,
            language=language,
            confidence_threshold=confidence,
            output_format=output_format,
            include_pdf_epub=include_pdf_epub,
            max_pages=max_pages,
            notebook_list=notebook_list
        )
        
        _display_text_extraction_results(results)
        
        # Export summary if output directory specified
        if output_dir and results:
            summary_file = Path(output_dir) / f"extraction_summary.{output_format}"
            
            if output_format == 'json':
                import json
                summary_data = {
                    'total_notebooks': len(results),
                    'successful': len([r for r in results.values() if r.success]),
                    'total_text_regions': sum(r.total_text_regions for r in results.values()),
                    'notebooks': {
                        uuid: {
                            'name': result.notebook_name,
                            'success': result.success,
                            'text_regions': result.total_text_regions,
                            'processing_time_ms': result.processing_time_ms,
                            'error': result.error_message if not result.success else None
                        } for uuid, result in results.items()
                    }
                }
                with open(summary_file, 'w') as f:
                    json.dump(summary_data, f, indent=2)
            
            elif output_format == 'csv':
                import pandas as pd
                summary_rows = []
                for uuid, result in results.items():
                    summary_rows.append({
                        'notebook_uuid': uuid,
                        'notebook_name': result.notebook_name,
                        'success': result.success,
                        'text_regions': result.total_text_regions,
                        'processing_time_ms': result.processing_time_ms,
                        'error_message': result.error_message if not result.success else ''
                    })
                df = pd.DataFrame(summary_rows)
                df.to_csv(summary_file, index=False)
            
            click.echo(f"\n📋 Summary saved to: {summary_file}")
        
        click.echo("\n🎉 Text extraction completed!")
        
    except Exception as e:
        click.echo(f"Text extraction failed: {e}", err=True)
        logging.exception("Text extraction error")
        sys.exit(1)


@text.command('analyze')
@click.argument('directory')
@click.option('--output', '-o', help='Output CSV file for analysis results')
@click.option('--cost-per-page', default=0.003, type=float, help='Estimated cost per page for OCR (default: $0.003)')
@click.option('--notebook-list', type=click.Path(exists=True), help='File containing notebook UUIDs or names to analyze (one per line)')
@click.pass_context
def analyze_library(ctx, directory: str, output: Optional[str], cost_per_page: float, notebook_list: Optional[str]):
    """Analyze reMarkable library without processing - dry run for cost estimation."""
    
    if not os.path.exists(directory):
        click.echo(f"Directory not found: {directory}", err=True)
        sys.exit(1)
    
    try:
        click.echo("🔍 Analyzing reMarkable library...")
        click.echo(f"📂 Input: {directory}")
        if output:
            click.echo(f"📄 Output: {output}")
        click.echo(f"💰 Cost per page: ${cost_per_page}")
        click.echo()
        
        results = analyze_remarkable_library(
            directory,
            output_file=output,
            cost_per_page=cost_per_page,
            notebook_list=notebook_list
        )
        
        # Display summary
        handwriting_notebooks = [r for r in results.values() 
                               if r.file_type == 'notebook' and not r.has_pdf_epub and r.page_count > 0]
        pdf_epub_notebooks = [r for r in results.values() 
                            if r.file_type in ['pdf', 'epub'] or r.has_pdf_epub]
        
        total_handwriting_pages = sum(r.page_count for r in handwriting_notebooks)
        total_estimated_cost = sum(r.estimated_cost for r in handwriting_notebooks)
        
        click.echo()
        click.echo("📊 Analysis Results:")
        click.echo(f"  Total items found: {len(results)}")
        click.echo(f"  📝 Handwriting notebooks (will be processed): {len(handwriting_notebooks)}")
        click.echo(f"  📄 PDF/EPUB notebooks (will be skipped): {len(pdf_epub_notebooks)}")
        click.echo(f"  📄 Total handwriting pages: {total_handwriting_pages}")
        click.echo(f"  💰 Estimated total cost: ${total_estimated_cost:.2f}")
        
        if handwriting_notebooks:
            click.echo()
            click.echo("📝 Top 10 handwriting notebooks by page count:")
            sorted_notebooks = sorted(handwriting_notebooks, key=lambda x: x.page_count, reverse=True)[:10]
            for i, notebook in enumerate(sorted_notebooks, 1):
                click.echo(f"  {i:2d}. {notebook.notebook_name} ({notebook.page_count} pages, ${notebook.estimated_cost:.2f})")
        
        if output:
            click.echo(f"\n📊 Detailed analysis saved to: {output}")
        
        click.echo("\n✅ Analysis completed!")
        
    except Exception as e:
        click.echo(f"Analysis failed: {e}", err=True)
        logging.exception("Analysis error")
        sys.exit(1)


@ocr.command('file')
@click.argument('file_path')
@click.option('--language', default='en', help='OCR language (default: en)')
@click.option('--confidence', default=0.7, type=float, help='Minimum confidence threshold (default: 0.7)')
@click.option('--show', is_flag=True, help='Display recognized text')
@click.pass_context
def ocr_file(ctx, file_path: str, language: str, confidence: float, show: bool):
    """Process a single file with OCR."""
    
    if not os.path.exists(file_path):
        click.echo(f"File not found: {file_path}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection() as conn:
            ocr_engine = OCREngine(conn, language=language, confidence_threshold=confidence)
            
            if not ocr_engine.is_available():
                click.echo("OCR engine not available. Please install EasyOCR and cairosvg:", err=True)
                click.echo("  poetry add easyocr cairosvg", err=True)
                sys.exit(1)
            
            if not ocr_engine.can_process(file_path):
                click.echo(f"Cannot process file: {file_path}", err=True)
                click.echo("File must be a .rm file or notebook .content file")
                sys.exit(1)
            
            click.echo(f"Processing with OCR (language: {language}, confidence: {confidence})...")
            result = ocr_engine.process_file(file_path)
            
            if result.success:
                ocr_results = result.ocr_results
                click.echo(f"Recognized {len(ocr_results)} text regions")
                
                if show and ocr_results:
                    click.echo(f"\nRecognized text:")
                    for i, ocr_result in enumerate(ocr_results, 1):
                        confidence_pct = ocr_result.confidence * 100
                        page = ocr_result.page_number or "Unknown"
                        click.echo(f"\n{i}. Page {page} (confidence: {confidence_pct:.1f}%):")
                        click.echo(f"   {ocr_result.text}")
            else:
                click.echo(f"OCR processing failed: {result.error_message}", err=True)
                sys.exit(1)
                
    except Exception as e:
        click.echo(f"OCR processing failed: {e}", err=True)
        logging.exception("OCR processing error")
        sys.exit(1)


@ocr.command('pdf-directory')
@click.argument('directory')
@click.option('--language', default='en', help='OCR language (default: en)')
@click.option('--confidence', default=0.7, type=float, help='Minimum confidence threshold (default: 0.7)')
@click.option('--export', help='Export OCR results to CSV file')
@click.pass_context
def ocr_pdf_directory(ctx, directory: str, language: str, confidence: float, export: Optional[str]):
    """Process directory of PDF files with OCR for handwritten text recognition."""
    
    if not os.path.exists(directory):
        click.echo(f"Directory not found: {directory}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        # Check if PDF OCR is available
        with db_manager.get_connection() as conn:
            pdf_ocr_engine = PDFOCREngine(conn, language=language, confidence_threshold=confidence)
            if not pdf_ocr_engine.is_available():
                click.echo("PDF OCR engine not available. Please install EasyOCR and pdf2image:", err=True)
                click.echo("  poetry add easyocr pdf2image", err=True)
                sys.exit(1)
        
        click.echo(f"Processing PDF directory with OCR (language: {language}, confidence: {confidence})...")
        results = process_directory_with_pdf_ocr(
            directory, 
            db_manager, 
            language=language, 
            confidence_threshold=confidence
        )
        
        total_regions = sum(results.values())
        processed_files = len([count for count in results.values() if count > 0])
        
        click.echo(f"\nPDF OCR Processing Results:")
        click.echo(f"  Files processed: {len(results)}")
        click.echo(f"  Files with text: {processed_files}")
        click.echo(f"  Total text regions: {total_regions}")
        
        if total_regions > 0:
            click.echo(f"\nResults by file:")
            for file_path, count in results.items():
                if count > 0:
                    file_name = os.path.basename(file_path)
                    click.echo(f"  {file_name}: {count} text regions")
        
        # Export if requested
        if export:
            click.echo(f"\nExporting PDF OCR results to {export}...")
            with db_manager.get_connection() as conn:
                pdf_ocr_engine = PDFOCREngine(conn)
                pdf_ocr_engine.export_ocr_results_to_csv(export)
            click.echo("Export completed")
            
    except Exception as e:
        click.echo(f"PDF OCR processing failed: {e}", err=True)
        logging.exception("PDF OCR processing error")
        sys.exit(1)


@ocr.command('pdf-file')
@click.argument('file_path')
@click.option('--language', default='en', help='OCR language (default: en)')
@click.option('--confidence', default=0.7, type=float, help='Minimum confidence threshold (default: 0.7)')
@click.option('--show', is_flag=True, help='Display recognized text')
@click.pass_context
def ocr_pdf_file(ctx, file_path: str, language: str, confidence: float, show: bool):
    """Process a single PDF file with OCR."""
    
    if not os.path.exists(file_path):
        click.echo(f"File not found: {file_path}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection() as conn:
            pdf_ocr_engine = PDFOCREngine(conn, language=language, confidence_threshold=confidence)
            
            if not pdf_ocr_engine.is_available():
                click.echo("PDF OCR engine not available. Please install EasyOCR and pdf2image:", err=True)
                click.echo("  poetry add easyocr pdf2image", err=True)
                sys.exit(1)
            
            if not pdf_ocr_engine.can_process(file_path):
                click.echo(f"Cannot process file: {file_path}", err=True)
                click.echo("File must be a PDF file")
                sys.exit(1)
            
            click.echo(f"Processing PDF with OCR (language: {language}, confidence: {confidence})...")
            result = pdf_ocr_engine.process_file(file_path)
            
            if result.success:
                ocr_results = result.ocr_results
                click.echo(f"Recognized {len(ocr_results)} text regions")
                
                if show and ocr_results:
                    click.echo(f"\nRecognized text:")
                    for i, ocr_result in enumerate(ocr_results, 1):
                        confidence_pct = ocr_result.confidence * 100
                        page = ocr_result.page_number or "Unknown"
                        click.echo(f"\n{i}. Page {page} (confidence: {confidence_pct:.1f}%):")
                        click.echo(f"   {ocr_result.text}")
            else:
                click.echo(f"PDF OCR processing failed: {result.error_message}", err=True)
                sys.exit(1)
                
    except Exception as e:
        click.echo(f"PDF OCR processing failed: {e}", err=True)
        logging.exception("PDF OCR processing error")
        sys.exit(1)


def _find_remarkable_sync_directory(config_obj, fallback_dir: str) -> Optional[str]:
    """Find the best reMarkable sync directory for metadata updates."""
    
    # 1. Try configured sync directory first
    configured_sync = config_obj.get('remarkable.sync_directory')
    if configured_sync and os.path.exists(configured_sync):
        return configured_sync
    
    # 2. Try common reMarkable Desktop sync locations
    import platform
    system = platform.system()
    
    common_paths = []
    if system == "Darwin":  # macOS
        home = os.path.expanduser("~")
        common_paths = [
            f"{home}/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop",
            f"{home}/.remarkable",
            f"{home}/Documents/reMarkable"
        ]
    elif system == "Windows":
        home = os.path.expanduser("~")
        common_paths = [
            f"{home}\\AppData\\Local\\remarkable\\desktop",
            f"{home}\\Documents\\reMarkable"
        ]
    elif system == "Linux":
        home = os.path.expanduser("~")
        common_paths = [
            f"{home}/.local/share/remarkable/desktop",
            f"{home}/.remarkable",
            f"{home}/Documents/reMarkable"
        ]
    
    # Check each common path
    for path in common_paths:
        if os.path.exists(path) and os.path.isdir(path):
            # Quick check - does it have .metadata files?
            import glob
            if glob.glob(os.path.join(path, "*.metadata")):
                return path
    
    # 3. Check if fallback directory has metadata files
    if fallback_dir and os.path.exists(fallback_dir):
        import glob
        if glob.glob(os.path.join(fallback_dir, "*.metadata")):
            return fallback_dir
    
    # 4. No valid directory found
    return None


@cli.command('process-all')
@click.argument('directory')
@click.option('--output-dir', help='Directory to save extracted text files')
@click.option('--export-highlights', help='Export highlights to CSV file')
@click.option('--export-text', help='Export extracted text to CSV file')
@click.option('--database', help='Database path (overrides config)')
@click.option('--language', default='en', help='OCR language (default: en)')
@click.option('--confidence', default=0.7, type=float, help='Minimum confidence threshold (default: 0.7)')
@click.option('--format', 'output_format', type=click.Choice(['txt', 'md', 'json', 'csv']), default='md', help='Output format for text files (default: md)')
@click.option('--enhanced-highlights', is_flag=True, help='Use enhanced highlight extraction with EPUB matching')
@click.option('--include-pdf-epub', is_flag=True, help='Include notebooks with PDF/EPUB files in text extraction')
@click.option('--max-pages', type=int, help='Maximum pages to process per notebook (for testing)')
@click.option('--skip-metadata-update', is_flag=True, help='Skip automatic metadata update (faster but may use stale data)')
@click.pass_context
def process_all(ctx, directory: str, output_dir: Optional[str], export_highlights: Optional[str], 
                export_text: Optional[str], database: Optional[str], language: str, confidence: float, output_format: str,
                enhanced_highlights: bool, include_pdf_epub: bool, max_pages: Optional[int],
                skip_metadata_update: bool):
    """Process directory with both handwritten text extraction AND highlight extraction."""
    
    if not os.path.exists(directory):
        click.echo(f"Directory not found: {directory}", err=True)
        sys.exit(1)
    
    config_obj = ctx.obj['config']
    db_path = database or config_obj.get('database.path')
    
    try:
        click.echo("🚀 Starting combined processing: handwritten notes + PDF/EPUB highlights")
        click.echo(f"📂 Input directory: {directory}")
        if output_dir:
            click.echo(f"📁 Text output directory: {output_dir}")
        if export_highlights:
            click.echo(f"📄 Highlights export: {export_highlights}")
        if export_text:
            click.echo(f"📄 Text export: {export_text}")
        click.echo()
        
        db_manager = DatabaseManager(db_path)
        
        # Step 0: Auto-update metadata (unless skipped)
        if not skip_metadata_update:
            click.echo("📊 Step 0: Updating notebook metadata...")
            
            # Try to find reMarkable sync directory for metadata
            metadata_dir = _find_remarkable_sync_directory(config_obj, directory)
            
            if metadata_dir:
                try:
                    from ..core.notebook_paths import update_notebook_metadata
                    
                    # Get data directory from config  
                    data_dir = config_obj.get('remarkable.data_directory', './data')
                    
                    with db_manager.get_connection() as conn:
                        updated_count = update_notebook_metadata(metadata_dir, conn, data_dir)
                    
                    click.echo(f"✅ Updated {updated_count} notebook metadata records")
                except Exception as e:
                    click.echo(f"⚠️  Warning: Could not update metadata: {e}")
                    click.echo("   Continuing with existing metadata...")
            else:
                click.echo("⚠️  Warning: Could not find reMarkable sync directory")
                click.echo("   Use 'update-paths' command manually if needed")
            
            click.echo()
        else:
            click.echo("⏭️  Skipping metadata update (using existing data)")
            click.echo()
        
        # Step 1: Extract handwritten text
        click.echo("📝 Step 1: Extracting handwritten text from notebooks...")
        text_results = extract_text_from_directory(
            directory,
            output_dir=output_dir,
            db_path=db_path,
            language=language,
            confidence_threshold=confidence,
            output_format=output_format,
            include_pdf_epub=include_pdf_epub,
            max_pages=max_pages
        )
        
        click.echo(f"✅ Text extraction completed: {len([r for r in text_results.values() if r.success])} notebooks processed")
        
        # Step 2: Extract highlights from PDF/EPUB
        click.echo("\n📖 Step 2: Extracting highlights from PDF/EPUB documents...")
        
        if enhanced_highlights:
            from ..processors.enhanced_highlight_extractor import process_directory_enhanced
            highlight_results = process_directory_enhanced(directory, db_manager)
            highlight_type = "enhanced passages"
        else:
            from ..processors.highlight_extractor import process_directory
            highlight_results = process_directory(directory, db_manager)
            highlight_type = "highlights"
        
        total_highlights = sum(highlight_results.values())
        click.echo(f"✅ Highlight extraction completed: {total_highlights} {highlight_type} from {len(highlight_results)} files")
        
        # Step 3: Export results if requested
        if export_highlights or export_text:
            click.echo("\n📤 Step 3: Exporting results...")
            
            with db_manager.get_connection() as conn:
                if export_highlights:
                    if enhanced_highlights:
                        from ..processors.enhanced_highlight_extractor import EnhancedHighlightExtractor
                        extractor = EnhancedHighlightExtractor(conn)
                        extractor.export_enhanced_highlights_to_csv(export_highlights)
                    else:
                        from ..processors.highlight_extractor import HighlightExtractor
                        extractor = HighlightExtractor(conn)
                        extractor.export_highlights_to_csv(export_highlights)
                    click.echo(f"   ✅ Highlights exported to: {export_highlights}")
                
                if export_text:
                    # Export text extraction results
                    import pandas as pd
                    text_rows = []
                    for uuid, result in text_results.items():
                        if result.success:
                            text_rows.append({
                                'notebook_uuid': uuid,
                                'notebook_name': result.notebook_name,
                                'text_regions': result.total_text_regions,
                                'processing_time_ms': result.processing_time_ms,
                                'success': True
                            })
                        else:
                            text_rows.append({
                                'notebook_uuid': uuid,
                                'notebook_name': result.notebook_name,
                                'text_regions': 0,
                                'processing_time_ms': result.processing_time_ms,
                                'success': False,
                                'error': result.error_message
                            })
                    
                    if text_rows:
                        df = pd.DataFrame(text_rows)
                        df.to_csv(export_text, index=False)
                        click.echo(f"   ✅ Text extraction results exported to: {export_text}")
        
        # Step 4: Display summary
        click.echo(f"\n🎉 Combined processing completed successfully!")
        click.echo(f"📊 Summary:")
        click.echo(f"   📝 Handwritten notebooks: {len([r for r in text_results.values() if r.success])}/{len(text_results)} successful")
        click.echo(f"   📖 PDF/EPUB highlights: {total_highlights} {highlight_type} from {len([c for c in highlight_results.values() if c > 0])} documents")
        
        if output_dir:
            click.echo(f"   📁 Text files saved to: {output_dir}")
        
        total_text_regions = sum(r.total_text_regions for r in text_results.values() if r.success)
        if total_text_regions > 0:
            click.echo(f"   📝 Total text regions extracted: {total_text_regions}")
        
    except Exception as e:
        click.echo(f"Combined processing failed: {e}", err=True)
        logging.exception("Combined processing error")
        sys.exit(1)


@cli.command('update-paths')
@click.option('--remarkable-dir', help='reMarkable directory path (overrides config)')
@click.pass_context
def update_notebook_paths(ctx, remarkable_dir: Optional[str]):
    """Update notebook folder paths from reMarkable directory."""
    
    config_obj = ctx.obj['config']
    
    # Use provided directory or get from config
    if not remarkable_dir:
        remarkable_dir = config_obj.get('remarkable.sync_directory')
    
    if not remarkable_dir:
        click.echo("❌ Error: No reMarkable directory specified", err=True)
        click.echo("Set via config or use --remarkable-dir option", err=True)
        sys.exit(1)
    
    if not os.path.exists(remarkable_dir):
        click.echo(f"❌ Error: Directory not found: {remarkable_dir}", err=True)
        sys.exit(1)
    
    try:
        from ..core.notebook_paths import update_notebook_metadata
        from ..core.database import DatabaseManager
        
        db_path = config_obj.get('database.path')
        db_manager = DatabaseManager(db_path)
        
        click.echo(f"📂 Scanning reMarkable directory: {remarkable_dir}")
        
        # Get data directory from config
        data_dir = config_obj.get('remarkable.data_directory', './data')
        
        with db_manager.get_connection() as conn:
            updated_count = update_notebook_metadata(remarkable_dir, conn, data_dir)
        
        click.echo(f"✅ Updated {updated_count} notebook metadata records in database")
        
        # Show some examples with metadata
        click.echo("\n📄 Example notebook metadata:")
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT visible_name, full_path, last_modified, last_opened_page, pinned
                FROM notebook_metadata 
                WHERE item_type = 'DocumentType' 
                ORDER BY last_modified DESC
                LIMIT 5
            """)
            
            for name, path, last_mod, last_page, pinned in cursor.fetchall():
                pin_icon = "📌" if pinned else "📄"
                # Convert timestamp to readable format
                if last_mod and last_mod != "0":
                    try:
                        import datetime
                        timestamp = int(last_mod) / 1000  # Convert from milliseconds
                        date_str = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                    except:
                        date_str = "unknown"
                else:
                    date_str = "never"
                    
                click.echo(f"   {pin_icon} {name}")
                click.echo(f"      Path: {path}")
                click.echo(f"      Modified: {date_str}, Page: {last_page or 0}")
                click.echo()
        
    except Exception as e:
        click.echo(f"❌ Error updating notebook paths: {e}", err=True)
        logging.exception("Update paths error")
        sys.exit(1)


@cli.command('export')
@click.option('--output', '-o', required=True, help='Output CSV file path')
@click.option('--enhanced', is_flag=True, help='Export enhanced highlights')
@click.option('--ocr', is_flag=True, help='Export OCR results')
@click.option('--title', help='Filter by document title')
@click.option('--source-file', help='Filter by source file path')
@click.pass_context
def export_data(ctx, output: str, enhanced: bool, ocr: bool, title: Optional[str], source_file: Optional[str]):
    """Export highlights or OCR results to CSV file."""
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection() as conn:
            if ocr:
                ocr_engine = OCREngine(conn)
                ocr_engine.export_ocr_results_to_csv(output, source_file)
                item_type = "OCR results"
            elif enhanced:
                extractor = EnhancedHighlightExtractor(conn)
                extractor.export_enhanced_highlights_to_csv(output, title)
                item_type = "enhanced highlights"
            else:
                extractor = HighlightExtractor(conn)
                extractor.export_highlights_to_csv(output, title)
                item_type = "highlights"
        
        click.echo(f"{item_type.title()} exported to {output}")
        
        if title:
            click.echo(f"(filtered by title: {title})")
        elif source_file:
            click.echo(f"(filtered by source file: {source_file})")
            
    except Exception as e:
        click.echo(f"Export failed: {e}", err=True)
        sys.exit(1)




@cli.command('watch')
@click.option('--source-directory', help='reMarkable app directory to watch (overrides config)')
@click.option('--local-directory', help='Local sync directory (overrides config)')
@click.option('--database', help='Database path (overrides config)')
@click.option('--sync-on-startup', is_flag=True, default=True, help='Perform initial sync on startup')
@click.option('--process-immediately', is_flag=True, default=True, help='Process files immediately after sync')
@click.pass_context
def watch_directory(ctx, source_directory: Optional[str], local_directory: Optional[str], 
                   database: Optional[str], sync_on_startup: bool, process_immediately: bool):
    """Watch reMarkable directory for changes and process automatically with two-tier system."""
    
    config_obj = ctx.obj['config']
    
    # Import here to avoid circular imports
    from ..core.file_watcher import ReMarkableWatcher
    from ..processors.notebook_text_extractor import NotebookTextExtractor
    
    # Override config with command line options if provided
    if source_directory:
        config_obj.set('remarkable.source_directory', source_directory)
    if local_directory:
        config_obj.set('remarkable.local_sync_directory', local_directory)
    if database:
        config_obj.set('database.path', database)
    
    # Validate configuration
    source_dir = config_obj.get('remarkable.source_directory')
    local_sync_dir = config_obj.get('remarkable.local_sync_directory', './data/remarkable_sync')
    
    if not source_dir:
        click.echo("❌ Source directory not configured", err=True)
        click.echo("Set remarkable.source_directory in config or use --source-directory option")
        click.echo("\nExample locations:")
        click.echo("  macOS: ~/Library/Containers/com.remarkable.desktop/Data/Documents/remarkable")
        click.echo("  Windows: %APPDATA%/remarkable/desktop")
        click.echo("  Linux: ~/.local/share/remarkable/desktop")
        sys.exit(1)
    
    if not os.path.exists(source_dir):
        click.echo(f"❌ Source directory not found: {source_dir}", err=True)
        click.echo("Make sure the reMarkable desktop app is installed and has synced data")
        sys.exit(1)
    
    # Setup database and text extractor
    db_path = config_obj.get('database.path')
    db_manager = DatabaseManager(db_path)
    
    # Initialize text extractor with database manager for thread safety
    text_extractor = NotebookTextExtractor(
        data_directory=local_sync_dir,
        db_manager=db_manager
    )
    
    # Initialize the two-tier watcher system
    try:
        click.echo("🚀 Starting reMarkable two-tier watching system...")
        click.echo(f"📁 Source: {source_dir}")
        click.echo(f"🔄 Local sync: {local_sync_dir}")
        click.echo(f"⚙️  Sync on startup: {'Yes' if sync_on_startup else 'No'}")
        click.echo(f"⚡ Process immediately: {'Yes' if process_immediately else 'No'}")
        click.echo()
        
        # Create watcher
        watcher = ReMarkableWatcher(config_obj)
        watcher.set_text_extractor(text_extractor)
        
        # Start the system
        import asyncio
        
        async def run_watcher():
            """Run the watcher system."""
            try:
                success = await watcher.start()
                
                if not success:
                    click.echo("❌ Failed to start watching system", err=True)
                    return False
                
                click.echo("✅ Two-tier watching system started successfully!")
                click.echo("📡 Monitoring reMarkable app directory for changes...")
                click.echo("🔄 Syncing to local directory and processing automatically...")
                click.echo("\n💡 The system will:")
                click.echo("   1. Watch your reMarkable app directory for changes")
                click.echo("   2. Automatically rsync changes to local directory") 
                click.echo("   3. Process changed notebooks with incremental updates")
                click.echo("   4. Extract text using AI-powered OCR")
                click.echo("\nPress Ctrl+C to stop watching...")
                
                # Keep running until interrupted
                try:
                    while watcher.is_running:
                        await asyncio.sleep(1)
                except KeyboardInterrupt:
                    click.echo("\n\n🛑 Stopping watcher...")
                    await watcher.stop()
                    click.echo("✅ Watcher stopped")
                    return True
                    
            except Exception as e:
                click.echo(f"❌ Error in watcher: {e}", err=True)
                logger.exception("Watcher error")
                return False
        
        # Run the async watcher
        result = asyncio.run(run_watcher())
        sys.exit(0 if result else 1)
        
    except KeyboardInterrupt:
        click.echo("\n🛑 Interrupted by user")
        sys.exit(0)
    except Exception as e:
        click.echo(f"❌ Failed to start watcher: {e}", err=True)
        logger.exception("Watch command error")
        sys.exit(1)


@cli.command('version')
def version():
    """Show version information."""
    try:
        # Try to read version from pyproject.toml
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        
        pyproject_path = project_root / 'pyproject.toml'
        
        if pyproject_path.exists():
            with open(pyproject_path, 'rb') as f:
                data = tomllib.load(f)
                version_str = data.get('tool', {}).get('poetry', {}).get('version', 'unknown')
        else:
            version_str = 'development'
    except ImportError:
        version_str = 'development'
    except Exception:
        version_str = 'unknown'
    
    click.echo(f"reMarkable Integration CLI v{version_str}")
    click.echo(f"Python {sys.version}")


def main():
    """Main entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        click.echo(f"\nUnexpected error: {e}", err=True)
        logging.exception("Unexpected CLI error")
        sys.exit(1)


if __name__ == '__main__':
    main()