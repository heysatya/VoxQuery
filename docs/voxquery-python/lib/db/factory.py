import json
import os
from functools import lru_cache
from lib.db.types import DBAdapter

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "db_config.json")

with open(_CONFIG_PATH) as f:
    _CONFIG = json.load(f)


def get_active_provider_config() -> dict:
    active_key = _CONFIG["active_provider"]
    provider_config = _CONFIG["providers"].get(active_key)
    if not provider_config:
        raise RuntimeError(
            f'db_config.json: active_provider "{active_key}" has no matching entry under "providers". '
            f'Valid options: {list(_CONFIG["providers"].keys())}'
        )
    return provider_config


def get_query_source_config() -> dict:
    return _CONFIG["query_sources"]


@lru_cache(maxsize=1)
def get_db_adapter() -> DBAdapter:
    """
    The only place that reads `active_provider`. Everything downstream
    (validator, executor, pipeline) talks to the DBAdapter interface only —
    swapping backend databases means editing config/db_config.json, not code.
    Cached with lru_cache so repeated calls within one process reuse the
    same adapter instance.
    """
    provider_config = get_active_provider_config()
    connection_string = os.environ.get(provider_config["connection_env_var"])
    if not connection_string:
        raise RuntimeError(
            f'Missing required env var "{provider_config["connection_env_var"]}" for the active provider. '
            f"Set it in .env / your platform's project settings — never commit it to db_config.json."
        )

    adapter_type = provider_config["adapter"]
    if adapter_type == "postgres":
        from lib.db.providers.postgres import PostgresAdapter
        return PostgresAdapter(connection_string)
    elif adapter_type == "snowflake":
        from lib.db.providers.snowflake import SnowflakeAdapter
        return SnowflakeAdapter(connection_string)
    elif adapter_type == "mysql":
        from lib.db.providers.mysql import MySQLAdapter
        return MySQLAdapter(connection_string)
    else:
        raise RuntimeError(f'Unknown adapter type "{adapter_type}" in db_config.json')
