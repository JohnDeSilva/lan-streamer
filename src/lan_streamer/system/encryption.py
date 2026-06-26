import base64
import hashlib
import logging
import os
from pathlib import Path
from cryptography.fernet import Fernet

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_KEY_FILE_PATH: Path = Path.home() / ".config" / "lan-streamer" / "secret.key"


def _derive_fernet_key(raw_key: str) -> bytes:
    """Derives a stable 32-byte url-safe base64-encoded key from a raw string using SHA-256."""
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(hashed_key)


def get_encryption_key() -> bytes:
    """Retrieves or generates the symmetric encryption key.

    Checks environment variable LAN_STREAMER_SECRET_KEY first.
    If not set, loads from the default key file (generating a new key if the file does not exist).
    """
    environment_key = os.environ.get("LAN_STREAMER_SECRET_KEY")
    if environment_key:
        logger.debug(
            "Using encryption key from environment variable LAN_STREAMER_SECRET_KEY"
        )
        try:
            # Check if it's already a valid Fernet key (32 bytes base64url encoded)
            decoded_key = base64.urlsafe_b64decode(environment_key.encode("utf-8"))
            if len(decoded_key) == 32:
                return environment_key.encode("utf-8")
        except Exception:
            pass
        return _derive_fernet_key(environment_key)

    key_file_path = DEFAULT_KEY_FILE_PATH
    if key_file_path.exists():
        try:
            file_content = key_file_path.read_text(encoding="utf-8").strip()
            decoded_key = base64.urlsafe_b64decode(file_content.encode("utf-8"))
            if len(decoded_key) == 32:
                logger.debug(f"Loaded encryption key from file: {key_file_path}")
                return file_content.encode("utf-8")
            else:
                logger.warning(
                    f"Key file {key_file_path} contains invalid key length. Deriving key."
                )
                return _derive_fernet_key(file_content)
        except Exception as error:
            logger.error(
                f"Error reading encryption key file: {error}. Deriving temporary key."
            )

    # Generate a new key and save it
    try:
        new_key = Fernet.generate_key()
        key_file_path.parent.mkdir(parents=True, exist_ok=True)
        # Write key with 0o600 permissions (read/write only by owner)
        file_descriptor = os.open(
            str(key_file_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as key_file:
            key_file.write(new_key.decode("utf-8"))
        logger.info(f"Generated new encryption key and saved to {key_file_path}")
        return new_key
    except Exception as error:
        logger.exception(
            f"Failed to generate and save encryption key to {key_file_path}: {error}"
        )
        # Return a fallback derived key based on machine/user details so we don't crash
        fallback_source = (
            f"{os.getlogin() if hasattr(os, 'getlogin') else 'default'}-{Path.home()}"
        )
        return _derive_fernet_key(fallback_source)


def encrypt_secret(plain_text: str) -> str:
    """Encrypts plain text using Fernet symmetric encryption."""
    if not plain_text:
        return plain_text
    try:
        key = get_encryption_key()
        fernet_cipher = Fernet(key)
        encrypted_bytes = fernet_cipher.encrypt(plain_text.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception as error:
        logger.exception("Failed to encrypt secret data")
        raise error


def decrypt_secret(cipher_text: str) -> str:
    """Decrypts cipher text using Fernet symmetric encryption."""
    if not cipher_text:
        return cipher_text
    try:
        key = get_encryption_key()
        fernet_cipher = Fernet(key)
        decrypted_bytes = fernet_cipher.decrypt(cipher_text.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as error:
        logger.error(
            "Failed to decrypt secret data. The encryption key might be incorrect or missing."
        )
        raise error
