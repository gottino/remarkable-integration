#!/usr/bin/env python3
"""
Setup verification script for reMarkable Pipeline
This script checks that all files are in the right place and imports work correctly.
"""

import os
import sys
from pathlib import Path
import importlib.util

def check_file_exists(file_path: str, description: str) -> bool:
    """Check if a file exists and report status."""
    if os.path.exists(file_path):
        print(f"✅ {description}: {file_path}")
        return True
    else:
        print(f"❌ {description}: {file_path} (NOT FOUND)")
        return False

def check_import(module_name: str, from_path: str = None) -> bool:
    """Check if a module can be imported."""
    try:
        if from_path:
            # Import from specific path
            spec = importlib.util.spec_from_file_location(module_name, from_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            # Import normally
            __import__(module_name)
        print(f"✅ Import {module_name}: SUCCESS")
        return True
    except Exception as e:
        print(f"❌ Import {module_name}: FAILED ({e})")
        return False

def main():
    """Run verification checks."""
    print("🔍 reMarkable Pipeline Setup Verification")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists("pyproject.toml"):
        print("❌ Not in project root directory!")
        print("   Please run this script from the directory containing pyproject.toml")
        sys.exit(1)
    
    print("✅ Running from project root directory")
    print()
    
    # Check project structure
    print("📁 Checking Project Structure:")
    structure_ok = True
    
    # Essential directories
    dirs = [
        ("src", "Source code directory"),
        ("src/processors", "Processors directory"),
        ("scripts", "Scripts directory"),
        ("examples", "Examples directory")
    ]
    
    for dir_path, description in dirs:
        if os.path.exists(dir_path):
            print(f"✅ {description}: {dir_path}/")
        else:
            print(f"❌ {description}: {dir_path}/ (MISSING)")
            structure_ok = False
    
    print()
    
    # Check essential files
    print("📄 Checking Essential Files:")
    files_ok = True
    
    files = [
        ("extract_text.py", "Original extraction script"),
        ("src/processors/highlight_extractor.py", "New highlight extractor"),
        ("scripts/migrate_highlights.py", "Migration script"),
        ("examples/highlight_extraction_demo.py", "Demo script")
    ]
    
    for file_path, description in files:
        if not check_file_exists(file_path, description):
            files_ok = False
    
    print()
    
    # Check imports
    print("📦 Checking Imports:")
    imports_ok = True
    
    # Check original extract_text.py
    if os.path.exists("extract_text.py"):
        if not check_import("extract_text"):
            imports_ok = False
    
    # Check new system imports
    sys.path.insert(0, os.getcwd())  # Add project root to path
    
    import_tests = [
        ("src.processors.highlight_extractor", None),
        ("pandas", None),
        ("watchdog", None)
    ]
    
    for module, path in import_tests:
        if not check_import(module, path):
            imports_ok = False
    
    print()
    
    # Check Poetry environment
    print("🎭 Checking Poetry Environment:")
    poetry_ok = True
    
    # Check if we're in a Poetry environment
    virtual_env = os.environ.get('VIRTUAL_ENV')
    if virtual_env and 'pypoetry' in virtual_env:
        print("✅ Running in Poetry virtual environment")
    else:
        print("⚠️  Not running in Poetry virtual environment")
        print("   Run 'poetry shell' or use 'poetry run python verify_setup.py'")
    
    print()
    
    # Overall status
    print("📋 Verification Summary:")
    print("=" * 30)
    
    if structure_ok and files_ok and imports_ok:
        print("🎉 ALL CHECKS PASSED!")
        print("   Your setup is ready to use.")
        print()
        print("🚀 Next Steps:")
        print("   1. Set up database: poetry run python scripts/database_setup.py --setup")
        print("   2. Test migration: poetry run python scripts/migrate_highlights.py /test/path --compare")
        print("   3. Run demo: poetry run python examples/highlight_extraction_demo.py --interactive")
    else:
        print("❌ SOME CHECKS FAILED!")
        print("   Please fix the issues above before proceeding.")
        
        if not structure_ok:
            print("   - Create missing directories")
        if not files_ok:
            print("   - Copy artifact code to the specified files")
        if not imports_ok:
            print("   - Install missing dependencies: poetry install")
            print("   - Check that extract_text.py is in the project root")
    
    print()
    print("📖 For detailed setup instructions, see:")
    print("   - README.md (if available)")
    print("   - docs/highlight_extraction.md (if available)")

if __name__ == "__main__":
    main()