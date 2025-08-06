#!/usr/bin/env python3
"""
Migration script to help transition from the original extract_text.py
to the new modular highlight extractor system.

This script:
1. Uses your existing extract_text.py logic as a fallback
2. Demonstrates how to migrate to the new system
3. Provides backward compatibility for existing workflows
4. Shows performance comparisons between old and new approaches
"""

import os
import sys
import time
import pandas as pd
from pathlib import Path

# Import your original functions
try:
    from extract_text import (
        find_content_and_rm_files,
        process_rm_files,
        extract_ascii_text,
        clean_extracted_text
    )
    ORIGINAL_MODULE_AVAILABLE = True
except ImportError:
    print("Warning: Original extract_text.py not found. Some features will be unavailable.")
    ORIGINAL_MODULE_AVAILABLE = False

# Import new system (adjust path as needed)
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from src.processors.highlight_extractor import HighlightExtractor, process_directory
    from src.core.database import DatabaseManager
    NEW_SYSTEM_AVAILABLE = True
except ImportError:
    print("Warning: New highlight extractor system not found.")
    NEW_SYSTEM_AVAILABLE = False


class HighlightMigrationTool:
    """Tool to help migrate from old to new highlight extraction system."""
    
    def __init__(self):
        self.db_manager = None
        self.highlight_extractor = None
        
        if NEW_SYSTEM_AVAILABLE:
            # Initialize new system
            self.db_manager = DatabaseManager("migration_test.db")
            self.highlight_extractor = HighlightExtractor(self.db_manager)
    
    def compare_extraction_methods(self, directory: str) -> Dict:
        """Compare old vs new extraction methods."""
        if not ORIGINAL_MODULE_AVAILABLE or not NEW_SYSTEM_AVAILABLE:
            print("Cannot compare - both systems must be available")
            return {}
        
        print(f"🔄 Comparing extraction methods on directory: {directory}")
        
        results = {
            'old_method': {},
            'new_method': {},
            'timing': {},
            'differences': []
        }
        
        # Test old method
        print("\n📊 Testing original method...")
        start_time = time.time()
        
        try:
            content_to_rm_files = find_content_and_rm_files(directory)
            old_highlights = []
            
            for content_file, rm_files in content_to_rm_files.items():
                result_df = process_rm_files(rm_files, content_file)
                if not result_df.empty:
                    old_highlights.extend(result_df.to_dict('records'))
            
            results['old_method'] = {
                'highlight_count': len(old_highlights),
                'file_count': len(content_to_rm_files),
                'highlights': old_highlights
            }
            
        except Exception as e:
            print(f"❌ Error in old method: {e}")
            results['old_method'] = {'error': str(e)}
        
        old_time = time.time() - start_time
        results['timing']['old_method'] = old_time
        
        # Test new method
        print("📊 Testing new method...")
        start_time = time.time()
        
        try:
            file_results = process_directory(directory, self.db_manager)
            
            # Get all highlights from database
            new_highlights = []
            for file_path in file_results.keys():
                content_id = os.path.splitext(os.path.basename(file_path))[0]
                
                # Get document info to find title
                try:
                    with open(file_path, 'r') as f:
                        content_data = json.load(f)
                    
                    # Get title from metadata
                    metadata_file = os.path.join(os.path.dirname(file_path), f"{content_id}.metadata")
                    title = "Unknown Title"
                    if os.path.exists(metadata_file):
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            title = metadata.get('visibleName', title)
                    
                    doc_highlights = self.highlight_extractor.get_highlights_for_document(title)
                    new_highlights.extend(doc_highlights)
                    
                except Exception as e:
                    print(f"Warning: Could not get highlights for {file_path}: {e}")
            
            results['new_method'] = {
                'highlight_count': len(new_highlights),
                'file_count': len(file_results),
                'highlights': new_highlights
            }
            
        except Exception as e:
            print(f"❌ Error in new method: {e}")
            results['new_method'] = {'error': str(e)}
        
        new_time = time.time() - start_time
        results['timing']['new_method'] = new_time
        
        # Compare results
        if 'error' not in results['old_method'] and 'error' not in results['new_method']:
            old_count = results['old_method']['highlight_count']
            new_count = results['new_method']['highlight_count']
            
            print(f"\n📋 Comparison Results:")
            print(f"  Original method: {old_count} highlights in {old_time:.2f}s")
            print(f"  New method: {new_count} highlights in {new_time:.2f}s")
            print(f"  Difference: {new_count - old_count} highlights")
            print(f"  Speed improvement: {((old_time - new_time) / old_time * 100):.1f}%")
            
            # Find textual differences (simplified)
            old_texts = {h.get('Extracted Sentence', h.get('text', '')) for h in results['old_method']['highlights']}
            new_texts = {h.get('text', h.get('Extracted Sentence', '')) for h in results['new_method']['highlights']}
            
            only_in_old = old_texts - new_texts
            only_in_new = new_texts - old_texts
            
            if only_in_old:
                print(f"  Only in old method: {len(only_in_old)} highlights")
                results['differences'].append(f"Old method found {len(only_in_old)} unique highlights")
            
            if only_in_new:
                print(f"  Only in new method: {len(only_in_new)} highlights")
                results['differences'].append(f"New method found {len(only_in_new)} unique highlights")
        
        return results
    
    def migrate_to_new_system(self, directory: str, output_csv: str = None) -> bool:
        """Migrate from old to new system, preserving CSV output compatibility."""
        if not NEW_SYSTEM_AVAILABLE:
            print("❌ New system not available for migration")
            return False
        
        print(f"🚀 Migrating directory to new system: {directory}")
        
        try:
            # Process with new system
            results = process_directory(directory, self.db_manager)
            
            if not results:
                print("⚠️ No files processed")
                return False
            
            total_highlights = sum(results.values())
            print(f"✅ Processed {len(results)} files, extracted {total_highlights} highlights")
            
            # Export to CSV if requested (backward compatibility)
            if output_csv:
                print(f"📄 Exporting to CSV: {output_csv}")
                self.highlight_extractor.export_highlights_to_csv(output_csv)
                print("✅ CSV export completed")
            
            return True
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            return False
    
    def create_compatibility_csv(self, directory: str, output_csv: str) -> None:
        """Create CSV in the same format as original extract_text.py."""
        if not NEW_SYSTEM_AVAILABLE:
            print("❌ New system not available")
            return
        
        print(f"📄 Creating compatibility CSV: {output_csv}")
        
        try:
            # Get all highlights from database
            all_highlights = []
            
            # Process directory to ensure highlights are in database
            results = process_directory(directory, self.db_manager)
            
            # Export in original format
            with self.db_manager.get_connection() as conn:
                query = '''
                    SELECT title as "Title", 
                           file_name as "File Name",
                           text as "Extracted Sentence",
                           page_number as "Page Number"
                    FROM highlights 
                    ORDER BY title, page_number, created_at
                '''
                
                df = pd.read_sql_query(query, conn)
                df.to_csv(output_csv, index=False)
                
                print(f"✅ Created compatibility CSV with {len(df)} highlights")
                print(f"   Format matches original extract_text.py output")
                
        except Exception as e:
            print(f"❌ Error creating compatibility CSV: {e}")
    
    def run_side_by_side_test(self, directory: str) -> None:
        """Run both old and new methods side by side for testing."""
        print("🔬 Running side-by-side comparison test")
        
        if not ORIGINAL_MODULE_AVAILABLE:
            print("❌ Original extract_text.py not available - running new method only")
            if NEW_SYSTEM_AVAILABLE:
                self.migrate_to_new_system(directory, "new_method_output.csv")
            return
        
        if not NEW_SYSTEM_AVAILABLE:
            print("❌ New system not available - running original method only")
            self._run_original_method(directory)
            return
        
        # Run comparison
        results = self.compare_extraction_methods(directory)
        
        # Create outputs from both methods
        print("\n📁 Creating output files...")
        
        # Original method output
        try:
            content_to_rm_files = find_content_and_rm_files(directory)
            all_results = []
            
            for content_file, rm_files in content_to_rm_files.items():
                result_df = process_rm_files(rm_files, content_file)
                if not result_df.empty:
                    all_results.append(result_df)
            
            if all_results:
                combined_df = pd.concat(all_results, ignore_index=True)
                combined_df.to_csv("original_method_output.csv", index=False)
                print("✅ Original method output: original_method_output.csv")
            
        except Exception as e:
            print(f"❌ Error creating original output: {e}")
        
        # New method output
        self.create_compatibility_csv(directory, "new_method_output.csv")
        
        print("\n🎯 Comparison complete! Check the output files to see differences.")
    
    def _run_original_method(self, directory: str) -> None:
        """Run only the original method."""
        print("🔄 Running original extract_text.py method...")
        
        try:
            content_to_rm_files = find_content_and_rm_files(directory)
            
            if not content_to_rm_files:
                print("❌ No .content files with corresponding .rm files found!")
                return
            
            all_results = []
            
            for content_file, rm_files in content_to_rm_files.items():
                print(f"Processing: {os.path.basename(content_file)}")
                result_df = process_rm_files(rm_files, content_file)
                
                if not result_df.empty:
                    all_results.append(result_df)
                    content_id = os.path.splitext(os.path.basename(content_file))[0]
                    output_csv = os.path.join(directory, f"{content_id}_extracted_text_with_pages.csv")
                    result_df.to_csv(output_csv, index=False)
                    print(f"✅ Saved: {output_csv}")
                else:
                    print(f"⚪ No highlights found")
            
            # Create combined output
            if all_results:
                combined_df = pd.concat(all_results, ignore_index=True)
                combined_output = os.path.join(directory, "all_extracted_highlights.csv")
                combined_df.to_csv(combined_output, index=False)
                print(f"📄 Combined output: {combined_output}")
                print(f"📊 Total highlights extracted: {len(combined_df)}")
            
        except Exception as e:
            print(f"❌ Error running original method: {e}")


def main():
    """Main entry point for migration tool."""
    import argparse
    
    parser = argparse.ArgumentParser(description="reMarkable Highlight Extraction Migration Tool")
    
    parser.add_argument("directory", help="Directory containing .content and .rm files")
    
    parser.add_argument(
        "--compare", 
        action="store_true",
        help="Compare old vs new extraction methods"
    )
    
    parser.add_argument(
        "--migrate",
        action="store_true", 
        help="Migrate to new system"
    )
    
    parser.add_argument(
        "--original-only",
        action="store_true",
        help="Run original extract_text.py method only"
    )
    
    parser.add_argument(
        "--output-csv",
        help="Output CSV file path"
    )
    
    parser.add_argument(
        "--compatibility",
        action="store_true",
        help="Create CSV in original format for backward compatibility"
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.directory):
        print(f"❌ Directory does not exist: {args.directory}")
        sys.exit(1)
    
    # Initialize migration tool
    migration_tool = HighlightMigrationTool()
    
    # Run based on arguments
    if args.compare:
        migration_tool.compare_extraction_methods(args.directory)
    
    elif args.migrate:
        success = migration_tool.migrate_to_new_system(args.directory, args.output_csv)
        if not success:
            sys.exit(1)
    
    elif args.original_only:
        migration_tool._run_original_method(args.directory)
    
    elif args.compatibility:
        output_csv = args.output_csv or "highlights_compatibility.csv"
        migration_tool.create_compatibility_csv(args.directory, output_csv)
    
    else:
        # Default: run side-by-side test
        migration_tool.run_side_by_side_test(args.directory)


if __name__ == "__main__":
    main()