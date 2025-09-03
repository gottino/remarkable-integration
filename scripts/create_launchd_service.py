#!/usr/bin/env python3
"""
Create a launchd service for automatically starting the reMarkable file watcher
"""

import os
import sys
from pathlib import Path
import plistlib

def create_launchd_service():
    """Create a launchd plist file for the reMarkable watcher service"""
    
    # Get current project directory
    project_root = Path(__file__).parent.parent.resolve()
    
    # Get the user's home directory
    home_dir = Path.home()
    launch_agents_dir = home_dir / "Library" / "LaunchAgents"
    
    # Create LaunchAgents directory if it doesn't exist
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    
    # Service configuration
    service_name = "com.remarkable.integration.watcher"
    plist_file = launch_agents_dir / f"{service_name}.plist"
    
    # Get Python executable path from poetry
    import subprocess
    try:
        poetry_python = subprocess.check_output(
            ["poetry", "env", "info", "--path"], 
            cwd=project_root,
            text=True
        ).strip()
        python_path = Path(poetry_python) / "bin" / "python"
    except subprocess.CalledProcessError:
        # Fallback to system python
        python_path = sys.executable
    
    # Create the plist configuration
    plist_config = {
        "Label": service_name,
        "ProgramArguments": [
            str(python_path),
            "-m", "src.cli.main",
            "watch",
            "--sync-on-startup",
            "--process-immediately"
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(home_dir / "Library" / "Logs" / "remarkable-watcher.log"),
        "StandardErrorPath": str(home_dir / "Library" / "Logs" / "remarkable-watcher-error.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(home_dir),
        }
    }
    
    # Write the plist file
    with open(plist_file, 'wb') as f:
        plistlib.dump(plist_config, f)
    
    print(f"✅ Created launchd service file: {plist_file}")
    print(f"📁 Working directory: {project_root}")
    print(f"🐍 Python path: {python_path}")
    print(f"📝 Logs will be written to:")
    print(f"   Output: ~/Library/Logs/remarkable-watcher.log")
    print(f"   Errors: ~/Library/Logs/remarkable-watcher-error.log")
    
    # Create logs directory
    logs_dir = home_dir / "Library" / "Logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n🚀 To start the service:")
    print(f"   launchctl load {plist_file}")
    print(f"\n🛑 To stop the service:")
    print(f"   launchctl unload {plist_file}")
    print(f"\n📊 To check service status:")
    print(f"   launchctl list | grep {service_name}")
    print(f"\n📝 To view logs:")
    print(f"   tail -f ~/Library/Logs/remarkable-watcher.log")
    
    return plist_file

if __name__ == "__main__":
    plist_file = create_launchd_service()
    
    # Ask if user wants to load the service immediately
    import sys
    response = input(f"\nWould you like to load the service now? (y/N): ").strip().lower()
    
    if response in ['y', 'yes']:
        import subprocess
        try:
            subprocess.run(["launchctl", "load", str(plist_file)], check=True)
            print("✅ Service loaded successfully!")
            print("The watcher will now start automatically after restarts.")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to load service: {e}")
            print("You can load it manually with:")
            print(f"   launchctl load {plist_file}")
    else:
        print("Service created but not loaded.")
        print("Load it manually when ready with:")
        print(f"   launchctl load {plist_file}")