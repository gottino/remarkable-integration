#!/bin/bash

# Script to restore packages to their latest compatible versions
# Run this if packages were downgraded by overly restrictive version constraints

echo "🔄 Restoring packages to latest compatible versions..."

# Option 1: Update all packages to latest versions
echo "Choose restoration method:"
echo "1. Update ALL packages to latest versions (recommended)"
echo "2. Update only specific packages"  
echo "3. Show what would be updated without changing anything"
echo "4. Remove restrictive version constraints and reinstall"

read -p "Enter choice (1-4): " choice

case $choice in
    1)
        echo "📈 Updating all packages to latest versions..."
        poetry update
        echo "✅ All packages updated!"
        ;;
    2)
        echo "📋 Current packages that can be updated:"
        poetry show --outdated
        echo ""
        echo "Enter package names to update (space-separated):"
        read -r packages
        if [ -n "$packages" ]; then
            for package in $packages; do
                echo "📈 Updating $package..."
                poetry update "$package"
            done
        fi
        ;;
    3)
        echo "📋 Showing what would be updated (dry run)..."
        poetry update --dry-run
        ;;
    4)
        echo "🔧 Removing restrictive constraints and reinstalling..."
        echo "This will edit your pyproject.toml to use more flexible constraints"
        
        # Backup pyproject.toml
        cp pyproject.toml pyproject.toml.backup
        echo "💾 Backed up pyproject.toml to pyproject.toml.backup"
        
        # Use sed to make version constraints more flexible
        # This converts exact versions like "^1.3.0" to ">=1.3.0"
        # and removes overly restrictive constraints
        
        echo "🔧 Making version constraints more flexible..."
        
        # Create a more flexible version
        sed -i.tmp 's/pandas = "\^2\.2\.0"/pandas = ">=2.2.0"/' pyproject.toml
        sed -i.tmp 's/numpy = "\^1\.26\.0"/numpy = ">=1.26.0"/' pyproject.toml
        sed -i.tmp 's/watchdog = "\^2\.1\.0"/watchdog = ">=2.0.0"/' pyproject.toml
        sed -i.tmp 's/pydantic = "\^2\.9\.0"/pydantic = ">=2.9.0"/' pyproject.toml
        sed -i.tmp 's/loguru = "\^0\.6\.0"/loguru = ">=0.6.0"/' pyproject.toml
        
        # Remove temporary file
        rm -f pyproject.toml.tmp
        
        # Update lock file and install
        echo "🔄 Updating lock file..."
        poetry lock --no-update
        poetry install
        
        echo "📈 Now updating to latest versions..."
        poetry update
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "📊 Final package status:"
poetry show --tree

echo ""
echo "✅ Package restoration complete!"
echo ""
echo "💡 Next steps:"
echo "1. Test your application: poetry run python -m pytest"
echo "2. Check highlight extraction: poetry run python examples/highlight_extraction_demo.py --interactive"