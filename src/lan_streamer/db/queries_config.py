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


def get_app_config(key: str, default: Any = None) -> Any:
    """Returns the stored value for *key* from app_config, coerced to its declared type."""
    try:
        logger.debug(f"Executing DB query get_app_config: key='{key}'")
        with get_session() as session:
            row = session.scalars(
                select(AppConfig).where(AppConfig.key == key)
            ).one_or_none()
            if row is None or row.value is None:
                logger.debug(
                    f"No value stored for app_config key '{key}' — returning default value"
                )
                # Seed the default into the DB so the key exists going forward.
                if default is not None:
                    set_app_config(key, default)
                return default
            coerce = _TYPE_COERCIONS.get(row.type or "str", str)
            val = coerce(row.value)
            logger.debug(f"get_app_config query response: key='{key}' -> value={val}")
            return val
    except Exception:
        logger.warning(
            f"Error reading app_config key '{key}' — returning default value"
        )
        return default


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


def get_secret(secret_type: SecretType) -> Dict[str, Any]:
    """Returns the credential payload dict for *secret_type*."""
    try:
        logger.debug(f"Executing DB query get_secret: secret_type={secret_type}")
        with get_session() as session:
            row = session.scalars(
                select(AppSecret).where(AppSecret.secret_type == secret_type.value)
            ).one_or_none()
            if row is None or not row.secret:
                logger.debug(
                    f"No secret stored for type '{secret_type}' — returning empty dict"
                )
                return {}
            res = json.loads(row.secret)
            logger.debug(
                f"get_secret query response for type={secret_type}: [MASKED payload keys: {list(res.keys())}]"
            )
            return res
    except Exception:
        logger.warning(
            f"Error reading secret for type '{secret_type}' — returning empty dict"
        )
        return {}


def get_all_secrets() -> Dict[str, Dict[str, Any]]:
    """Returns all app_secrets rows as a dictionary of secret_type string -> payload dict."""
    try:
        logger.debug("Executing DB query get_all_secrets")
        with get_session() as session:
            rows = session.scalars(select(AppSecret)).all()
            secrets_dict = {}
            for row in rows:
                if row.secret:
                    try:
                        secrets_dict[row.secret_type] = json.loads(row.secret)
                    except Exception:
                        logger.warning(
                            f"Error parsing secret for type '{row.secret_type}'"
                        )
            masked_dict = {k: list(v.keys()) for k, v in secrets_dict.items()}
            logger.debug(
                f"get_all_secrets query response: [MASKED secrets keys: {masked_dict}]"
            )
            return secrets_dict
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
            row = session.scalars(
                select(AppSecret).where(AppSecret.secret_type == secret_type.value)
            ).first()
            if row is None:
                row = AppSecret(secret_type=secret_type.value)
                session.add(row)
            row.secret = json.dumps(payload)
        logger.debug(f"Successfully saved secret to DB: secret_type={secret_type}")
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
