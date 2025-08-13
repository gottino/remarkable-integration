#!/bin/bash

# Quick commands to view your migration_test.db database content

echo "🔍 Quick Database Viewing Options for debug_final_test.db"
echo "======================================================"

DB_PATH="./debug_final_test.db"
if [ ! -f "$DB_PATH" ]; then
    DB_PATH="debug_final_test.db"
fi

if [ ! -f "$DB_PATH" ]; then
    echo "❌ migration_test.db not found in current directory or data/ folder"
    echo "   Please specify the correct path to your database"
    exit 1
fi

echo "📊 Database found: $DB_PATH"
echo ""

echo "🚀 Choose a viewing method:"
echo ""
echo "1️⃣  Python script (recommended):"
echo "   python view_database.py $DB_PATH"
echo ""
echo "2️⃣  SQLite command line:"
echo "   sqlite3 $DB_PATH"
echo "   Then type: .tables (to see tables)"
echo "   Then type: SELECT * FROM highlights; (to see highlights)"
echo "   Then type: .quit (to exit)"
echo ""
echo "3️⃣  Quick highlights view:"
echo "   sqlite3 -header -column $DB_PATH 'SELECT * FROM highlights LIMIT 10;'"
echo ""
echo "4️⃣  Export highlights to CSV:"
echo "   sqlite3 -header -csv $DB_PATH 'SELECT * FROM highlights;' > highlights_export.csv"
echo ""
echo "5️⃣  Python one-liner:"
echo "   python -c \"import sqlite3, pandas as pd; print(pd.read_sql('SELECT * FROM highlights', sqlite3.connect('$DB_PATH')))\""
echo ""

# Interactive menu
echo "Select an option (1-5) or press Enter to use Python script:"
read -r choice

case $choice in
    1|"")
        echo "🐍 Using Python database viewer..."
        if [ -f "view_database.py" ]; then
            python view_database.py "$DB_PATH"
        else
            echo "❌ view_database.py not found. Please create it from the artifact."
        fi
        ;;
    2)
        echo "💾 Opening SQLite command line..."
        echo "   Type .tables to see all tables"
        echo "   Type SELECT * FROM highlights; to see highlights" 
        echo "   Type .quit to exit"
        sqlite3 "$DB_PATH"
        ;;
    3)
        echo "⚡ Quick highlights preview:"
        sqlite3 -header -column "$DB_PATH" "SELECT title, text, page_number FROM highlights LIMIT 10;"
        ;;
    4)
        echo "📤 Exporting highlights to CSV..."
        sqlite3 -header -csv "$DB_PATH" "SELECT * FROM enhanced_highlights;" > enhanced_highlights_export.csv
        echo "✅ Exported to highlights_export.csv"
        ;;
    5)
        echo "🐍 Python one-liner results:"
        python -c "
import sqlite3
import pandas as pd
try:
    df = pd.read_sql('SELECT * FROM highlights', sqlite3.connect('$DB_PATH'))
    if len(df) > 0:
        print(f'Found {len(df)} highlights:')
        print(df.to_string(max_colwidth=50))
    else:
        print('No highlights found in database')
except Exception as e:
    print(f'Error: {e}')
"
        ;;
    *)
        echo "❌ Invalid choice"
        ;;
esac