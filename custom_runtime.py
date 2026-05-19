# custom_runtime.py - Runtime security hook
import sys
import os

def is_debugger_present() -> bool:
    """Check if a Python debugger is attached (e.g. pdb, pydevd)."""
    try:
        return hasattr(sys, 'gettrace') and sys.gettrace() is not None
    except Exception:
        return False

def verify_binary_integrity() -> bool:
    """
    Verify executable integrity using APP_EXPECTED_HASH env var.
    If the env var is not set we skip the check so dev/CI is unaffected.
    """
    expected_hash = os.environ.get('APP_EXPECTED_HASH', '').strip()
    if not expected_hash:
        return True  # No hash configured → skip

    try:
        import hashlib
        exe_path = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
        if not os.path.exists(exe_path):
            return True  # Can't verify a script path in dev
        hasher = hashlib.sha256()
        with open(exe_path, 'rb') as f:
            while chunk := f.read(4096):
                hasher.update(chunk)
        return hasher.hexdigest().lower() == expected_hash.lower()
    except Exception as e:
        print(f"Integrity check warning: {e}")
        return True  # Non-fatal in case of env issues

def secure_environment_check() -> bool:
    """
    Perform security checks. In DEV_MODE these are skipped so
    debuggers, coverage.py and test runners all work normally.
    """
    if os.environ.get('DEV_MODE', '').lower() in ('1', 'true', 'yes'):
        return True  # Developer bypass

    if is_debugger_present():
        # Warn but do NOT kill — let the app decide
        print("[security] Debugger detected.")

    if not verify_binary_integrity():
        print("[security] Integrity check failed — possible tampering.")
        return False

    return True

# Only abort if integrity is provably broken
if not secure_environment_check():
    sys.exit(1)
