"""Setup script - installs dependencies and verifies the environment."""

import subprocess
import sys
from pathlib import Path


def main():
    print("Music Manager - Setup")
    print("=" * 40)

    # Install dependencies
    print("\nInstalling Python dependencies...")
    req_file = Path(__file__).parent / "requirements.txt"
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: pip install failed:\n{result.stderr}")
        return False
    print("Dependencies installed successfully.")

    # Try to find flac.exe
    print("\nLooking for flac.exe...")
    from encoder import find_flac_exe
    flac_path = find_flac_exe()
    if flac_path:
        print(f"Found flac.exe at: {flac_path}")
    else:
        print("WARNING: flac.exe not found. Please install FLAC or set the path in settings.")
        print("  Download from: https://xiph.org/flac/download.html")

    # Initialize database
    print("\nInitializing database...")
    from database import init_db
    init_db()
    print("Database ready.")

    print("\n" + "=" * 40)
    print("Setup complete! Run 'python app.py' to start the application.")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
