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
from pathlib import Path
from typing import Optional

import click

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import Config
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
@click.pass_context
def database_stats(ctx):
    """Show database statistics."""
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
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
@click.pass_context
def database_backup(ctx, output: Optional[str]):
    """Create database backup."""
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
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
@click.pass_context
def database_cleanup(ctx, days: int, vacuum: bool):
    """Clean up old data from database."""
    
    config_obj = ctx.obj['config']
    db_path = config_obj.get('database.path')
    
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
@click.pass_context
def process_directory(ctx, directory: str, enhanced: bool, export: Optional[str], compare: bool):
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
@click.option('--directory', help='Directory to watch (overrides config)')
@click.pass_context
def watch_directory(ctx, directory: Optional[str]):
    """Watch directory for file changes and process automatically."""
    
    config_obj = ctx.obj['config']
    
    if directory:
        watch_dir = directory
    else:
        watch_dir = config_obj.get('remarkable.sync_directory')
    
    if not watch_dir or not os.path.exists(watch_dir):
        click.echo("Watch directory not found or not configured", err=True)
        click.echo("Set remarkable.sync_directory in config or use --directory option")
        sys.exit(1)
    
    click.echo(f"Watching directory: {watch_dir}")
    click.echo("Press Ctrl+C to stop")
    
    # This would require implementing the file watcher
    # For now, show a placeholder message
    click.echo("File watching not yet implemented")
    click.echo("Use 'remarkable-integration process directory' for batch processing")


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