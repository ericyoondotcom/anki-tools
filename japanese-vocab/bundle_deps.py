#!/usr/bin/env python3
"""
Script to bundle OpenAI and other dependencies for the Anki add-on.
Run this script to download and prepare the dependencies.
"""

import os
import sys
import subprocess
import shutil
import tempfile

def main():
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    vendor_dir = os.path.join(addon_dir, "vendor")
    
    # Remove existing vendor directory
    if os.path.exists(vendor_dir):
        shutil.rmtree(vendor_dir)
    
    # Create vendor directory
    os.makedirs(vendor_dir)
    
    # Dependencies to install
    dependencies = [
        "openai>=1.0.0",
        "typing-extensions",
        "httpx",
        "certifi",
        "anyio",
        "idna",
        "sniffio",
        "h11",
        "httpcore",
        "distro",
        "jiter",
        "tqdm"
    ]
    
    # Create a temporary directory for pip install
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Installing dependencies to {temp_dir}...")
        
        # Install dependencies to temporary directory
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--target", temp_dir,
            "--no-deps",  # Don't install sub-dependencies automatically
        ] + dependencies
        
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error installing dependencies: {e}")
            return 1
        
        # Copy only the packages we need to vendor directory
        for item in os.listdir(temp_dir):
            item_path = os.path.join(temp_dir, item)
            if os.path.isdir(item_path):
                # Copy directories (packages)
                dest_path = os.path.join(vendor_dir, item)
                shutil.copytree(item_path, dest_path)
                print(f"Copied {item} to vendor directory")
            elif item.endswith('.py'):
                # Copy Python files
                dest_path = os.path.join(vendor_dir, item)
                shutil.copy2(item_path, dest_path)
                print(f"Copied {item} to vendor directory")
    
    # Create __init__.py in vendor directory
    init_file = os.path.join(vendor_dir, "__init__.py")
    with open(init_file, "w") as f:
        f.write("# Vendored dependencies for Anki add-on\n")
    
    print(f"\nDependencies successfully bundled in {vendor_dir}")
    print("The add-on is now ready for use!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
