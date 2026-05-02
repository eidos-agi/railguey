"""TOTP guard for destructive operations.

Each machine gets a unique TOTP secret stored at ~/.railguey/totp_secret.
Before any destructive operation (delete, transfer), the caller must provide
the current TOTP code. This prevents AI agents from accidentally destroying
infrastructure without human confirmation.

Setup:
  1. railguey_totp_setup — generates secret, shows QR URI for authenticator app
  2. railguey_totp_verify — test that your code works

Usage in tools:
  from railguey.lib.totp import require_totp
  error = require_totp(code)
  if error:
      return error
"""

import hashlib
import hmac
import os
import struct
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".railguey"
SECRET_FILE = CONFIG_DIR / "totp_secret"


def _generate_secret(length: int = 20) -> bytes:
    return os.urandom(length)


def _base32_encode(data: bytes) -> str:
    """RFC 4648 base32 encoding without padding."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    result = []
    buffer = 0
    bits = 0
    for byte in data:
        buffer = (buffer << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            result.append(alphabet[(buffer >> bits) & 0x1F])
    if bits > 0:
        result.append(alphabet[(buffer << (5 - bits)) & 0x1F])
    return "".join(result)


def _hotp(secret: bytes, counter: int) -> str:
    """Generate a 6-digit HOTP code."""
    msg = struct.pack(">Q", counter)
    h = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def _totp(secret: bytes, period: int = 30) -> str:
    """Generate current TOTP code."""
    counter = int(time.time()) // period
    return _hotp(secret, counter)


def _load_secret() -> bytes | None:
    if not SECRET_FILE.is_file():
        return None
    return bytes.fromhex(SECRET_FILE.read_text().strip())


def _ascii_qr(data: str) -> str:
    """Generate a compact ASCII QR code using block characters."""
    try:
        import qrcode

        qr = qrcode.QRCode(box_size=1, border=1)
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.modules

        # Use Unicode block elements: top-half, bottom-half, full, empty
        # Process two rows at a time for compact output
        lines = []
        for r in range(0, len(matrix), 2):
            line = []
            for c in range(len(matrix[0])):
                top = matrix[r][c]
                bot = matrix[r + 1][c] if r + 1 < len(matrix) else False
                if top and bot:
                    line.append("\u2588")  # full block
                elif top:
                    line.append("\u2580")  # upper half
                elif bot:
                    line.append("\u2584")  # lower half
                else:
                    line.append(" ")
            lines.append("".join(line))
        return "\n".join(lines)
    except ImportError:
        return "(qrcode package missing)"


def _show_and_destroy_qr(uri: str) -> str:
    """Generate QR image, open it in Preview, delete after it's closed."""
    import subprocess
    import tempfile
    import threading

    try:
        import qrcode
    except ImportError:
        return "qrcode package missing — pip install qrcode[pil]"

    # Create temp file that won't auto-delete (we manage lifecycle)
    fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="railguey-totp-")
    os.close(fd)

    img = qrcode.make(uri)
    img.save(tmp_path)

    def _open_and_cleanup():
        # Open in Preview (blocking on macOS until Preview closes the file)
        subprocess.run(["open", "-W", tmp_path], check=False)
        # Preview closed — destroy the evidence
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Run in background so callers are not blocked while Preview is open.
    t = threading.Thread(target=_open_and_cleanup, daemon=True)
    t.start()

    return tmp_path


def setup() -> dict:
    """Generate and store a new TOTP secret. Shows QR in Preview, deletes on close."""
    secret = _generate_secret()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(secret.hex())
    SECRET_FILE.chmod(0o600)

    b32 = _base32_encode(secret)
    uri = f"otpauth://totp/Railguey?secret={b32}&issuer=Railguey&digits=6&period=30"

    # Show QR — opens Preview, deletes image when Preview is closed
    _show_and_destroy_qr(uri)

    return {
        "status": "TOTP configured",
        "secret_b32": b32,
        "otpauth_uri": uri,
        "qr_shown": True,
        "instructions": "QR code opened in Preview. Scan it now — the image is deleted when you close Preview.",
    }


def verify(code: str) -> dict:
    """Verify a TOTP code against the stored secret."""
    secret = _load_secret()
    if not secret:
        return {"error": "TOTP not configured. Run railguey_totp_setup first."}

    # Accept current and ±1 window for clock drift
    period = 30
    counter = int(time.time()) // period
    for offset in (-1, 0, 1):
        if _hotp(secret, counter + offset) == code.strip():
            return {"verified": True}

    return {"error": "Invalid TOTP code."}


def require_totp(code: str | None) -> dict | None:
    """Gate check — returns an error dict if TOTP fails, None if OK.

    Usage:
        error = require_totp(code)
        if error:
            return error
        # proceed with destructive operation
    """
    secret = _load_secret()
    if not secret:
        return {
            "error": "TOTP not configured. Destructive operations require TOTP. "
            "Run railguey_totp_setup to configure."
        }

    if not code:
        return {
            "error": "TOTP code required for this operation. "
            "Provide the current 6-digit code from your authenticator app."
        }

    result = verify(code)
    if "error" in result:
        return result

    return None  # All good
