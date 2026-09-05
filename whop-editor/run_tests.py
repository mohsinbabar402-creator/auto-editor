import sys
import unittest
from pathlib import Path

# Add whop-editor to sys.path
editor_root = Path(__file__).resolve().parent
sys.path.insert(0, str(editor_root))

if __name__ == "__main__":
    try:
        import pytest
        print("Running tests with pytest...")
        exit_code = pytest.main([str(editor_root / "tests"), "-v", "-s"])
        sys.exit(exit_code)
    except ImportError:
        print("pytest not available, running via unittest test discovery...")
        loader = unittest.TestLoader()
        suite = loader.discover(str(editor_root / "tests"), pattern="test_*.py")
        runner = unittest.TextTestRunner(verbosity=2)
        res = runner.run(suite)
        sys.exit(0 if res.wasSuccessful() else 1)
