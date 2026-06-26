import base64
import os
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet

from lan_streamer.system.encryption import (
    encrypt_secret,
    decrypt_secret,
    get_encryption_key,
    _derive_fernet_key,
)


def test_encrypt_decrypt_roundtrip() -> None:
    """Verifies that encrypting and decrypting returns the original text."""
    plain_text_message = "This is a super secure secret message!"
    cipher_text = encrypt_secret(plain_text_message)
    assert cipher_text != plain_text_message

    decrypted_content = decrypt_secret(cipher_text)
    assert decrypted_content == plain_text_message


def test_encrypt_decrypt_empty_values() -> None:
    """Verifies that empty string is handled correctly."""
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""


def test_get_encryption_key_from_environment(tmp_path: Path) -> None:
    """Verifies that the key is loaded from the LAN_STREAMER_SECRET_KEY environment variable."""
    # 1. Using a valid Fernet key
    generated_key = Fernet.generate_key().decode("utf-8")
    with patch.dict(os.environ, {"LAN_STREAMER_SECRET_KEY": generated_key}):
        loaded_key = get_encryption_key()
        assert loaded_key == generated_key.encode("utf-8")

    # 2. Using an arbitrary string (should derive a valid key)
    arbitrary_key_string = "my-custom-super-secret-key-phrase"
    with patch.dict(os.environ, {"LAN_STREAMER_SECRET_KEY": arbitrary_key_string}):
        derived_key = get_encryption_key()
        decoded_bytes = base64.urlsafe_b64decode(derived_key)
        assert len(decoded_bytes) == 32
        assert derived_key == _derive_fernet_key(arbitrary_key_string)


def test_get_encryption_key_from_file(tmp_path: Path) -> None:
    """Verifies that key is loaded from the fallback key file, or generated if missing."""
    temporary_key_file = tmp_path / "secret.key"

    with patch(
        "lan_streamer.system.encryption.DEFAULT_KEY_FILE_PATH", temporary_key_file
    ):
        # 1. When the file does not exist, it should generate and save a new key
        assert not temporary_key_file.exists()
        newly_generated_key = get_encryption_key()
        assert temporary_key_file.exists()

        file_content = temporary_key_file.read_text(encoding="utf-8").strip()
        assert file_content == newly_generated_key.decode("utf-8")

        if hasattr(os, "chmod"):
            file_mode = temporary_key_file.stat().st_mode
            assert (file_mode & 0o777) == 0o600

        # 2. When the file exists, it should load the existing key
        loaded_key = get_encryption_key()
        assert loaded_key == newly_generated_key
