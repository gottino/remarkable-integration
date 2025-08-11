#!/usr/bin/env python3
"""
Database viewer script for reMarkable Pipeline databases
This script allows you to view the contents of SQLite databases created by the pipeline.
"""

import sqlite3
import pandas as pd
import sys
import os
from pathlib import Path


def view_database(db_path: str):
    """View the contents of a SQLite database."""
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"📊 Database: {db_path}")
        print("=" * 60)
        
        # Get database info
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        
        if not tables:
            print("❌ No tables found in database")
            conn.close()
            return False
        
        print(f"📋 Found {len(tables)} tables: {', '.join(tables)}")
        print()
        
        # Show content of each table
        for table in tables:
            print(f"🗃️  Table: {table}")
            print("-" * 40)
            
            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"   Rows: {count}")
            
            if count > 0:
                # Get column info
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                col_names = [col[1] for col in columns]
                print(f"   Columns: {', '.join(col_names)}")
                
                # Show sample data (first 5 rows)
                cursor.execute(f"SELECT * FROM {table} LIMIT 5")
                rows = cursor.fetchall()
                
                if rows:
                    print("\n   📄 Sample data (first 5 rows):")
                    df = pd.DataFrame(rows, columns=col_names)
                    print(df.to_string(index=False, max_colwidth=50))
                
            print("\n")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error reading database: {e}")
        return False


def export_table_to_csv(db_path: str, table_name: str, output_path: str = None):
    """Export a specific table to CSV."""
    
    if not output_path:
        output_path = f"{table_name}.csv"
    
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        df.to_csv(output_path, index=False)
        conn.close()
        
        print(f"✅ Exported {len(df)} rows from {table_name} to {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error exporting table: {e}")
        return False


def export_all_tables(db_path: str, output_dir: str = "database_export"):
    """Export all tables to CSV files."""
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        return False
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        
        if not tables:
            print("❌ No tables found in database")
            conn.close()
            return False
        
        print(f"📤 Exporting {len(tables)} tables to {output_dir}/")
        
        for table in tables:
            output_file = os.path.join(output_dir, f"{table}.csv")
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            df.to_csv(output_file, index=False)
            print(f"   ✅ {table}: {len(df)} rows → {output_file}")
        
        conn.close()
        print(f"\n🎉 Export complete! Files saved in {output_dir}/")
        return True
        
    except Exception as e:
        print(f"❌ Error exporting tables: {e}")
        return False


def query_database(db_path: str, query: str):
    """Run a custom SQL query on the database."""
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        print(f"🔍 Query results ({len(df)} rows):")
        print("=" * 50)
        print(df.to_string(index=False))
        return True
        
    except Exception as e:
        print(f"❌ Error running query: {e}")
        return False


def main():
    """Main CLI interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description="View reMarkable Pipeline Database Contents")
    parser.add_argument("database", help="Path to the SQLite database file")
    
    parser.add_argument("--view", "-v", action="store_true", 
                       help="View database contents (default)")
    parser.add_argument("--export-table", "-t", 
                       help="Export specific table to CSV")
    parser.add_argument("--export-all", "-a", action="store_true",
                       help="Export all tables to CSV files")
    parser.add_argument("--query", "-q", 
                       help="Run custom SQL query")
    parser.add_argument("--output", "-o", 
                       help="Output file/directory path")
    
    args = parser.parse_args()
    
    # Default to view if no specific action
    if not any([args.export_table, args.export_all, args.query]):
        args.view = True
    
    if args.view:
        view_database(args.database)
    
    elif args.export_table:
        output_path = args.output or f"{args.export_table}.csv"
        export_table_to_csv(args.database, args.export_table, output_path)
    
    elif args.export_all:
        output_dir = args.output or "database_export"
        export_all_tables(args.database, output_dir)
    
    elif args.query:
        query_database(args.database, args.query)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Interactive mode if no arguments
        print("🔍 Database Viewer - Interactive Mode")
        print("=" * 40)
        
        # Find database files in common locations
        possible_dbs = [
            "migration_test.db",
            "data/migration_test.db", 
            "highlights_test.db",
            "remarkable_pipeline.db",
            "data/remarkable_pipeline.db"
        ]
        
        found_dbs = [db for db in possible_dbs if os.path.exists(db)]
        
        if found_dbs:
            print("📁 Found these databases:")
            for i, db in enumerate(found_dbs, 1):
                print(f"   {i}. {db}")
            
            try:
                choice = int(input(f"\nSelect database (1-{len(found_dbs)}): "))
                if 1 <= choice <= len(found_dbs):
                    selected_db = found_dbs[choice - 1]
                    print(f"\n📊 Viewing: {selected_db}")
                    view_database(selected_db)
                else:
                    print("❌ Invalid selection")
            except (ValueError, KeyboardInterrupt):
                print("❌ Invalid input or cancelled")
        else:
            print("❌ No databases found in common locations")
            print("   Try: python view_database.py /path/to/your/database.db")
    else:
        main()
