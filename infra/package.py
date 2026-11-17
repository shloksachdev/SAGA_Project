"""
Purpose: Packaging utility to bundle Lambda handler and common package into a deployment zip.
Phase: Phase 1
"""

import os
import sys
import zipfile


def build_zip(handler_file: str, output_zip: str):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    handler_path = os.path.join(base_dir, handler_file)
    common_path = os.path.join(base_dir, "common")
    zip_path = os.path.join(base_dir, output_zip)

    if not os.path.exists(handler_path):
        raise FileNotFoundError(f"Handler file {handler_path} not found.")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write handler at root of zip
        zf.write(handler_path, arcname=os.path.basename(handler_file))

        # Write common package
        for root, dirs, files in os.walk(common_path):
            # Skip __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, base_dir)
                zf.write(full_path, arcname=rel_path)

    print(f"[package] Built {output_zip} with handler {handler_file} and common/ package.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python package.py <handler_file> <output_zip>")
        sys.exit(1)
    build_zip(sys.argv[1], sys.argv[2])
