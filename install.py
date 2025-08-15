#!/usr/bin/env python3
"""
DaimalyadNodes - Post-installation setup script
This script runs after pip installs the package dependencies.
"""

import os
import sys
from pathlib import Path

def main():
    """Post-installation setup for DaimalyadNodes."""
    print("DaimalyadNodes: Post-installation setup...")
    
    # Get the package directory
    try:
        import daimalyadnodes
        package_dir = Path(daimalyadnodes.__file__).parent
    except ImportError:
        # Fallback: assume we're in the package directory
        package_dir = Path(__file__).parent
    
    print(f"Package directory: {package_dir}")
    
    # Verify the package structure
    required_files = [
        "__init__.py",
        "daimalyad_model_downloader.py", 
        "daimalyad_wildcard_processor.py"
    ]
    
    missing_files = []
    for file in required_files:
        if not (package_dir / file).exists():
            missing_files.append(file)
    
    if missing_files:
        print(f"Warning: Missing required files: {missing_files}")
        return False
    
    print("✓ All required files present")
    
    # Check if we're in a ComfyUI custom_nodes directory
    custom_nodes_dir = package_dir.parent
    if custom_nodes_dir.name == "custom_nodes":
        print("✓ Installed in ComfyUI custom_nodes directory")
    else:
        print("ℹ Package not in ComfyUI custom_nodes directory")
        print("  This is normal if installing for development")
    
    print("DaimalyadNodes: Setup complete!")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
