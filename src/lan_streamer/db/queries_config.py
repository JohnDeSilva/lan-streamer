import logging
import json
from typing import Dict, Any, Callable
from sqlalchemy import select

from lan_streamer.db.models import Series, AppConfig, AppSecret, SecretType

logger = logging.getLogger("lan_streamer.db.queries")


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


_TYPE_COERCIONS: Dict[str, Callable[[Any], Any]] = {
    "bool": lambda v: v == "1",
    "int": int,
    "float": float,
    "json": json.loads,
    "str": str,
}


def set_app_config(key: str, value: Any) -> None:
    """Upserts *value* for *key* in app_config."""
    try:
        logger.debug(f"Executing DB set_app_config: key='{key}', value='{value}'")
        with get_session() as session:
            row = session.scalars(
                select(AppConfig).where(AppConfig.key == key)
            ).one_or_none()

            if row is None:
                # Infer type hint from value
                if isinstance(value, bool):
                    type_hint = "bool"
                elif isinstance(value, int):
                    type_hint = "int"
                elif isinstance(value, float):
                    type_hint = "float"
                elif isinstance(value, (list, dict)):
                    type_hint = "json"
                else:
                    type_hint = "str"
                row = AppConfig(key=key, type=type_hint)
                session.add(row)

            # Serialise to TEXT
            hint = row.type or "str"
            if hint == "json":
                row.value = json.dumps(value)
            elif hint == "bool":
                row.value = "1" if value else "0"
            else:
                row.value = str(value)
        logger.debug(
            f"Successfully saved app_config in DB: key='{key}', value='{value}'"
        )
    except Exception:
        logger.exception(f"Error writing app_config key '{key}'")


def get_all_app_configs() -> Dict[str, Any]:
    """Returns all app_config rows as a dictionary of key -> coerced_value."""
    try:
        logger.debug("Executing DB query get_all_app_configs")
        with get_session() as session:
            rows = session.scalars(select(AppConfig)).all()
            config_dict = {}
            for row in rows:
                logger.info(
                    f"Reading app_config row: key='{row.key}', type='{row.type}', value='{row.value}'"
                )
                if row.value is not None:
                    coerce = _TYPE_COERCIONS.get(row.type or "str", str)
                    config_dict[row.key] = coerce(row.value)
            logger.debug(f"get_all_app_configs query response: {config_dict}")
            return config_dict
    except Exception:
        logger.warning("Error reading all app_config rows")
        return {}


def bulk_set_app_configs(config_dict: Dict[str, Any]) -> None:
    """Upserts all key/value pairs in config_dict into app_config in a single session."""
    try:
        logger.debug(
            f"Executing DB bulk_set_app_configs with config_dict: {config_dict}"
        )
        with get_session() as session:
            rows = session.scalars(select(AppConfig)).all()
            existing_map = {row.key: row for row in rows}

            for key, value in config_dict.items():
                row = existing_map.get(key)
                if row is None:
                    # Infer type hint from value
                    if isinstance(value, bool):
                        type_hint = "bool"
                    elif isinstance(value, int):
                        type_hint = "int"
                    elif isinstance(value, float):
                        type_hint = "float"
                    elif isinstance(value, (list, dict)):
                        type_hint = "json"
                    else:
                        type_hint = "str"
                    row = AppConfig(key=key, type=type_hint)
                    session.add(row)

                # Serialise to TEXT
                hint = row.type or "str"
                if hint == "json":
                    row.value = json.dumps(value)
                elif hint == "bool":
                    row.value = "1" if value else "0"
                else:
                    row.value = str(value)
            logging.info(f"Bulk upserted {len(config_dict)} app_config settings")
            logger.debug(f"Successfully saved bulk app_configs to DB: {config_dict}")
    except Exception:
        logger.exception("Error writing bulk app_config settings")


def get_all_secrets() -> Dict[str, Dict[str, Any]]:
    """Returns all app_secrets rows as a dictionary of secret_type string -> payload dict."""
    try:
        logger.debug("Executing DB query get_all_secrets")
        import uuid
        from sqlalchemy import text

        with get_session() as session:
            secret_rows = session.scalars(select(AppSecret)).all()
            secrets_dictionary = {}
            for secret_row in secret_rows:
                if secret_row.secret:
                    try:
                        secrets_dictionary[secret_row.secret_type] = json.loads(
                            secret_row.secret
                        )
                    except Exception:
                        logger.warning(
                            f"Error parsing secret for type '{secret_row.secret_type}'"
                        )

            # Check if any database value is stored in unencrypted plain text JSON
            # and transparently migrate it to encrypted representation.
            raw_records = session.execute(
                text("SELECT secret_uuid, secret FROM app_secrets")
            ).fetchall()
            for record_uuid, raw_secret in raw_records:
                if raw_secret and raw_secret.strip().startswith("{"):

                    def get_hex_representation(value: Any) -> str:
                        if isinstance(value, bytes):
                            return value.hex()
                        if isinstance(value, str):
                            try:
                                return uuid.UUID(value).hex
                            except Exception:
                                return value.encode("utf-8").hex()
                        return ""

                    raw_hex_representation = get_hex_representation(record_uuid)
                    for secret_row in secret_rows:
                        if (
                            get_hex_representation(secret_row.secret_uuid)
                            == raw_hex_representation
                        ):
                            # Re-assigning and flagging modified triggers SQLAlchemy TypeDecorator process_bind_param
                            secret_row.secret = raw_secret
                            from sqlalchemy.orm.attributes import flag_modified

                            flag_modified(secret_row, "secret")
                            session.add(secret_row)
                            logger.info(
                                f"Transparently encrypted legacy plain-text secret for type '{secret_row.secret_type}'"
                            )

            masked_dictionary = {
                secret_type_key: list(value_dictionary.keys())
                for secret_type_key, value_dictionary in secrets_dictionary.items()
            }
            logger.debug(
                f"get_all_secrets query response: [MASKED secrets keys: {masked_dictionary}]"
            )
            return secrets_dictionary
    except Exception:
        logger.warning("Error reading all secrets from database")
        return {}


def set_secret(secret_type: SecretType, payload: Dict[str, Any]) -> None:
    """Upserts the full credential payload for *secret_type*."""
    try:
        logger.debug(
            f"Executing DB set_secret: secret_type={secret_type}, [MASKED keys={list(payload.keys())}]"
        )
        with get_session() as session:
            secret_row = session.scalars(
                select(AppSecret).where(AppSecret.secret_type == secret_type.value)
            ).first()
            if secret_row is None:
                secret_row = AppSecret(secret_type=secret_type.value)
                session.add(secret_row)
            # The EncryptedString TypeDecorator will automatically encrypt this JSON string on write
            secret_row.secret = json.dumps(payload)
        logger.debug(
            f"Successfully saved encrypted secret to DB: secret_type={secret_type}"
        )
    except Exception:
        logger.exception(f"Error writing secret for type '{secret_type}'")


_SERIES_PREF_COLUMNS = {
    "hide_missing_future": "pref_hide_missing_future",
    "display_group_id": "pref_display_group_id",
}


def get_series_pref(
    library_name: str, series_name: str, key: str, default: Any = None
) -> Any:
    """Returns the per-series preference *key* for the given series."""
    col = _SERIES_PREF_COLUMNS.get(key)
    if col is None:
        logger.warning(f"Unknown series preference key: '{key}'")
        return default
    try:
        logger.debug(
            f"Executing DB query get_series_pref: library='{library_name}', "
            f"series='{series_name}', key='{key}'"
        )
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name,
                    Series.name == series_name,
                )
            ).first()
            if series is None:
                logger.debug(
                    f"get_series_pref response: series not found, returning default: {default}"
                )
                return default
            value = getattr(series, col, None)
            val = default if value is None else value
            logger.debug(f"get_series_pref query response: key='{key}' -> value={val}")
            return val
    except Exception:
        logger.exception(
            f"Error reading series pref '{key}' for '{library_name}:{series_name}'"
        )
        return default


def set_series_pref(library_name: str, series_name: str, key: str, value: Any) -> None:
    """Persists the per-series preference *key* = *value* for the given series."""
    col = _SERIES_PREF_COLUMNS.get(key)
    if col is None:
        logger.warning(f"Unknown series preference key: '{key}'")
        return
    try:
        logger.debug(
            f"Executing DB set_series_pref: library='{library_name}', "
            f"series='{series_name}', key='{key}', value='{value}'"
        )
        with get_session() as session:
            series = session.scalars(
                select(Series).where(
                    Series.library_name == library_name,
                    Series.name == series_name,
                )
            ).first()
            if series is None:
                logger.warning(
                    f"set_series_pref: series '{library_name}:{series_name}' not found"
                )
                return
            setattr(series, col, value)
        logger.debug(
            f"Successfully saved series_pref in DB: library='{library_name}', series='{series_name}', key='{key}'"
        )
    except Exception:
        logger.exception(
            f"Error writing series pref '{key}' for '{library_name}:{series_name}'"
        )
