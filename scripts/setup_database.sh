#!/bin/bash

# Quick start script for setting up the reMarkable Pipeline database
# Run this from your project root directory

echo "🚀 reMarkable Pipeline Database Setup"
echo "===================================="

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Please run this script from your project root directory (where pyproject.toml is located)"
    exit 1
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data
mkdir -p data/logs
mkdir -p data/backups
mkdir -p config
mkdir -p scripts

# Check if database setup script exists
if [ ! -f "scripts/database_setup.py" ]; then
    echo "❌ Database setup script not found. Please create scripts/database_setup.py first."
    echo "   (Copy the database_setup artifact content to this file)"
    exit 1
fi

# Set up the database
echo "🗃️ Setting up database..."
poetry run python scripts/database_setup.py --setup

# Check if setup was successful
if [ $? -eq 0 ]; then
    echo "✅ Database setup completed successfully!"
else
    echo "❌ Database setup failed. Check the error messages above."
    exit 1
fi

# Show database info
echo ""
echo "📊 Database Information:"
poetry run python scripts/database_setup.py --info

echo ""
echo "🎯 Next Steps:"
echo "1. Update your sync directory in the configuration:"
echo "   Edit config/database.yaml and set file_watcher.sync_directory"
echo ""
echo "2. Test highlight extraction:"
echo "   poetry run python examples/highlight_extraction_demo.py --interactive"
echo ""
echo "3. Process existing files:"
echo "   poetry run python scripts/migrate_highlights.py /path/to/remarkable/files --migrate"
echo ""
echo "4. Start the file watcher:"
echo "   poetry run python examples/highlight_extraction_demo.py --watch"

echo ""
echo "📋 Database Commands:"
echo "View database info:     poetry run python scripts/database_setup.py --info"
echo "Export data to CSV:     poetry run python scripts/database_setup.py --export data/export/"
echo "Optimize database:      poetry run python scripts/database_setup.py --vacuum"
echo "Recreate database:      poetry run python scripts/database_setup.py --setup --force-recreate"

echo ""
echo "✨ Database setup complete! Your reMarkable pipeline is ready to use."