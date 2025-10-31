#!/usr/bin/env python3
"""Testa imports básicos da aplicação."""
import sys

print("==> Testing imports...")

try:
    print("  - Testing app.core.config...")
    from app.core.config import settings
    print(f"     ✓ Config loaded, device: {settings.validate_device()}")
except Exception as e:
    print(f"     ✗ Error: {e}")
    sys.exit(1)

try:
    print("  - Testing app.core.storage...")
    from app.core.storage import storage
    print("     ✓ Storage module loaded")
except Exception as e:
    print(f"     ✗ Error: {e}")
    sys.exit(1)

try:
    print("  - Testing app.core.status...")
    from app.core.status import status_manager
    print("     ✓ Status manager loaded")
except Exception as e:
    print(f"     ✗ Error: {e}")
    sys.exit(1)

try:
    print("  - Testing app.core.queue...")
    from app.core.queue import enqueue_video_processing
    print("     ✓ Queue module loaded")
except Exception as e:
    print(f"     ✗ Error: {e}")
    sys.exit(1)

try:
    print("  - Testing app.main...")
    from app.main import app
    print("     ✓ FastAPI app loaded")
except Exception as e:
    print(f"     ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n==> All imports successful!")

