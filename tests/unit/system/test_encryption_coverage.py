"""Coverage tests for encryption.py — targeting uncovered lines."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from lan_streamer.system.encryption import (
    _derive_fernet_key,
    encrypt_secret,
    decrypt_secret,
    get_encryption_key,
)


class TestKeyFileInvalidLength:
    """Lines 48-53: key file with invalid decoded length."""

    def test_invalid_key_length_derives_key(self, tmp_path: Path) -> None:
        key_file = tmp_path / "secret.key"
        # Write a string that decodes to != 32 bytes
        short_key = base64.urlsafe_b64encode(b"short").decode("utf-8")
        key_file.write_text(short_key, encoding="utf-8")

        with patch("lan_streamer.system.encryption.DEFAULT_KEY_FILE_PATH", key_file):
            result = get_encryption_key()
            # Should have derived a key from the file content, not loaded it
            expected = _derive_fernet_key(short_key.strip())
            assert result == expected


class TestFallbackKeyGeneration:
    """Lines 69-77: fallback when key file generation fails."""

    def test_fallback_on_write_failure(self, tmp_path: Path) -> None:
        key_file = tmp_path / "nonexistent_parent" / "secret.key"

        with (
            patch("lan_streamer.system.encryption.DEFAULT_KEY_FILE_PATH", key_file),
            patch("os.open", side_effect=PermissionError("denied")),
        ):
            result = get_encryption_key()
            decoded = base64.urlsafe_b64decode(result)
            assert len(decoded) == 32


class TestEncryptException:
    """Lines 89-91: encrypt_secret exception handling."""

    def test_encrypt_failure_raises(self) -> None:
        with patch(
            "lan_streamer.system.encryption.get_encryption_key",
            side_effect=Exception("key error"),
        ):
            with pytest.raises(Exception, match="key error"):
                encrypt_secret("secret data")


class TestDecryptException:
    """Lines 103-107: decrypt_secret exception handling."""

    def test_decrypt_failure_raises(self) -> None:
        with patch("lan_streamer.system.encryption.get_encryption_key") as mock_key:
            mock_key.return_value = Fernet.generate_key()
            with pytest.raises(InvalidToken):
                decrypt_secret("this is not valid ciphertext")


class TestEnvVarValidKey:
    """Lines 27-34: env var with a valid 32-byte Fernet key."""

    def test_valid_fernet_key_from_env(self) -> None:
        valid_key = Fernet.generate_key().decode("utf-8")
        with patch.dict("os.environ", {"LAN_STREAMER_SECRET_KEY": valid_key}):
            result = get_encryption_key()
            assert result == valid_key.encode("utf-8")


class TestEnvVarInvalidKey:
    """Lines 35-37: env var with invalid base64 key is derived."""

    def test_invalid_env_key_is_derived(self) -> None:
        with patch.dict(
            "os.environ", {"LAN_STREAMER_SECRET_KEY": "not-a-valid-key!!!"}
        ):
            result = get_encryption_key()
            assert result == _derive_fernet_key("not-a-valid-key!!!")


class TestValidKeyFile:
    """Lines 44-46: key file with valid 32-byte decoded key."""

    def test_valid_key_from_file(self, tmp_path: Path) -> None:
        key_file = tmp_path / "secret.key"
        valid_key = Fernet.generate_key().decode("utf-8")
        key_file.write_text(valid_key, encoding="utf-8")

        with (
            patch("lan_streamer.system.encryption.DEFAULT_KEY_FILE_PATH", key_file),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = get_encryption_key()
            assert result == valid_key.encode("utf-8")


class TestKeyFileReadException:
    """Lines 52-55: exception reading key file."""

    def test_corrupt_key_file_generates_new(self, tmp_path: Path) -> None:
        key_file = tmp_path / "secret.key"
        key_file.write_text("not-valid-base64!!!", encoding="utf-8")

        with (
            patch("lan_streamer.system.encryption.DEFAULT_KEY_FILE_PATH", key_file),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = get_encryption_key()
            decoded = base64.urlsafe_b64decode(result)
            assert len(decoded) == 32


class TestEmptyStringEncryptDecrypt:
    """Lines 83, 97: encrypt/decrypt with empty string."""

    def test_encrypt_empty_returns_empty(self) -> None:
        assert encrypt_secret("") == ""

    def test_decrypt_empty_returns_empty(self) -> None:
        assert decrypt_secret("") == ""


class TestEncryptDecryptRoundTrip:
    """Lines 85-88, 99-102: successful encrypt/decrypt."""

    def test_round_trip(self) -> None:
        plain_text = "my secret password 123"
        encrypted = encrypt_secret(plain_text)
        assert encrypted != plain_text
        decrypted = decrypt_secret(encrypted)
        assert decrypted == plain_text
