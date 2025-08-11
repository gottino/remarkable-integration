#!/bin/bash

# Poetry commands to add the new dependencies for highlight extraction
# Run these from your project root directory

echo "📦 Adding core dependencies for highlight extraction..."

# Core dependencies (if not already present)
poetry add pandas@^1.3.0
poetry add numpy@^1.20.0
poetry add watchdog@^2.1.0
poetry add pydantic@^1.8.0
poetry add loguru@^0.6.0

echo "🧪 Adding development dependencies..."

# Development dependencies
poetry add --group dev pytest@^6.0.0
poetry add --group dev pytest-cov@^2.10.0
poetry add --group dev black@^22.0.0
poetry add --group dev isort@^5.10.0
poetry add --group dev flake8@^4.0.0

echo "⚡ Adding optional performance dependencies..."

# Optional dependencies for better performance
poetry add --optional pyarrow@^5.0.0

echo "📚 Adding optional documentation dependencies..."

# Optional documentation dependencies  
poetry add --optional mkdocs@^1.2.0
poetry add --optional mkdocs-material@^7.0.0

echo "✅ Dependencies added! Run 'poetry install' to install them."

# Install all dependencies
echo "🔄 Installing dependencies..."
poetry install

# Show the updated dependency tree
echo "📋 Current dependency status:"
poetry show --tree