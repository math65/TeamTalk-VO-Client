#!/usr/bin/env python3
"""
NUL Files Removal Script for Windows

This script finds and removes files named 'nul' which are problematic on Windows.
'nul' is a reserved device name in Windows (like CON, PRN, AUX) and cannot be
manipulated using standard file operations.

The script uses Windows UNC path syntax (\\?\) to bypass the reserved name
restriction and safely remove these files.

Usage:
    python remove_nul.py [directory]

    If no directory is specified, defaults to the script's directory
"""

import os
import sys
from pathlib import Path

def find_nul_files(root_path, verbose=True):
    """
    Recursively search for files named 'nul'.

    Args:
        root_path: The root directory to search from
        verbose: Whether to print search progress (default: True)

    Returns:
        List of paths to 'nul' files found
    """
    nul_files = []

    if verbose:
        print(f"Searching for 'nul' files in: {root_path}")
        print("-" * 60)

    try:
        # Walk through all directories
        for dirpath, _, filenames in os.walk(root_path):
            # Check for files named 'nul'
            if 'nul' in filenames:
                nul_file_path = os.path.join(dirpath, 'nul')
                nul_files.append(nul_file_path)
    except Exception as e:
        print(f"Warning: Error during search: {e}")

    return nul_files

def remove_nul_files(nul_files):
    """
    Remove the specified nul files.
    Uses Windows UNC path syntax (\\?\) to handle reserved names like 'nul'.

    Args:
        nul_files: List of file paths to remove

    Returns:
        Tuple of (removed_count, error_count)

    Notes:
        - Uses UNC path prefix (\\?\) to bypass Windows reserved name restrictions
        - Handles symlinks and junctions that may point to the same physical file
        - Returns count of removed files and errors encountered
    """
    removed_files = []
    errors = []

    if not nul_files:
        return 0, 0

    print("\nRemoving files...")
    print("-" * 60)

    for nul_file_path in nul_files:
        try:
            # Use pathlib to get absolute path WITHOUT resolving symlinks/junctions
            path_obj = Path(nul_file_path)
            # Get absolute path without resolving symlinks (use absolute() instead of resolve())
            abs_path = str(path_obj.absolute())

            # Normalize backslashes
            abs_path = abs_path.replace('/', '\\')

            # Add \\?\ prefix for Windows long path / reserved name support
            # This bypasses the Windows reserved name check
            unc_path = f"\\\\?\\{abs_path}"

            os.remove(unc_path)
            removed_files.append(nul_file_path)
            print(f"[OK] Removed: {nul_file_path}")
        except FileNotFoundError:
            # File might have been already deleted (symlink/junction pointing to same file)
            print(f"[SKIP] Already removed (symlink/junction): {nul_file_path}")
            removed_files.append(nul_file_path)
        except Exception as e:
            errors.append((nul_file_path, str(e)))
            print(f"[FAIL] Failed to remove: {nul_file_path}")
            print(f"  Error: {e}")

    # Summary
    print("-" * 60)
    print(f"\nSummary:")
    print(f"  Files removed: {len(removed_files)}")
    print(f"  Errors: {len(errors)}")

    if removed_files:
        print("\nRemoved files:")
        for file in removed_files:
            print(f"  - {file}")

    if errors:
        print("\nErrors:")
        for file, error in errors:
            print(f"  - {file}: {error}")

    return len(removed_files), len(errors)

def main():
    """Main execution function."""
    # Default to the directory where the script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = script_dir

    # Allow override via command line argument
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]

    # Validate directory exists
    if not os.path.exists(target_dir):
        print(f"Error: Directory '{target_dir}' does not exist!")
        sys.exit(1)

    if not os.path.isdir(target_dir):
        print(f"Error: '{target_dir}' is not a directory!")
        sys.exit(1)

    print("=" * 60)
    print("NUL Files Removal Script")
    print("=" * 60)
    print(f"Target directory: {target_dir}")
    print("=" * 60)

    try:
        # First, find all nul files
        nul_files = find_nul_files(target_dir)

        if not nul_files:
            print("\n[OK] No 'nul' files found!")
            sys.exit(0)

        # Display found files
        print(f"\nFound {len(nul_files)} 'nul' file(s):")
        print("-" * 60)
        for file in nul_files:
            print(f"  - {file}")
        print("-" * 60)

        # Auto-delete in non-interactive mode
        print(f"\nDeleting {len(nul_files)} file(s)...")
        print("")

        # Remove the files
        removed, errors = remove_nul_files(nul_files)

        # Final verification step
        print("\n" + "=" * 60)
        print("FINAL VERIFICATION")
        print("=" * 60)

        remaining_nul_files = find_nul_files(target_dir, verbose=False)

        if not remaining_nul_files:
            print("\n[SUCCESS] All 'nul' files have been removed!")
            print(f"  {removed} file(s) successfully deleted")
        else:
            print(f"\n[WARNING] {len(remaining_nul_files)} 'nul' file(s) remaining:")
            for file in remaining_nul_files:
                print(f"  - {file}")

        print("\n" + "=" * 60)

        if errors > 0 or remaining_nul_files:
            sys.exit(1)
        else:
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        print(f"Error type: {type(e).__name__}")
        sys.exit(1)


if __name__ == "__main__":
    main()
