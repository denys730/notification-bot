"""Enumerations shared by the API, the checkers and the MCP server."""

from enum import StrEnum


class CheckerCodes(StrEnum):
    """Every alert type this demo can be configured with.

    Adding one is the first step of adding a checker: the admin API's `/codes` endpoint, the MCP
    server's `list_checker_types`, and the registry guard test all read this enum.
    """

    HEARTBEAT = "heartbeat"
    THRESHOLD_BREACH = "threshold_breach"
    ACTIVITY_DROP = "activity_drop"
    STATUS_STUCK = "status_stuck"
    NEW_ENTITY_BREACH = "new_entity_breach"


class GlobalSettingNames(StrEnum):
    """Per-brand global settings, one `{name, value}` document each in the brand's database.

    The names are the ones the cadmin settings page reads, so it needs no changes. Only `regions` and
    `default_region` mean anything here (they back the region gate); the others are stored and
    returned untouched.
    """

    MIN_WIN_TO_STORE_EUR = "min_win_to_store_eur"
    BUSINESS_METRICS_MAX_LAG_SECONDS = "business_metrics_max_lag_seconds"
    REGIONS = "regions"
    DEFAULT_REGION = "default_region"
    CRYPTO_ADDRESS_MAX_PLAYERS_TO_PUBLISH = "crypto_address_max_players_to_publish"
    CRYPTO_ADDRESS_MAX_TRANSACTIONS_TO_PUBLISH = "crypto_address_max_transactions_to_publish"
    CRYPTO_ADDRESS_MAX_BALANCE_EUR_TO_PUBLISH = "crypto_address_max_balance_eur_to_publish"
    CRYPTO_ADDRESS_EXCLUDE_ENTITY_TAGS_REGEX = "crypto_address_exclude_entity_tags_regex"


GLOBAL_SETTINGS_DEFAULTS: dict[GlobalSettingNames, object] = {
    GlobalSettingNames.MIN_WIN_TO_STORE_EUR: None,
    GlobalSettingNames.BUSINESS_METRICS_MAX_LAG_SECONDS: 3600.0,
    GlobalSettingNames.REGIONS: [],
    GlobalSettingNames.DEFAULT_REGION: None,
    GlobalSettingNames.CRYPTO_ADDRESS_MAX_PLAYERS_TO_PUBLISH: 10,
    GlobalSettingNames.CRYPTO_ADDRESS_MAX_TRANSACTIONS_TO_PUBLISH: 100000,
    GlobalSettingNames.CRYPTO_ADDRESS_MAX_BALANCE_EUR_TO_PUBLISH: 1000000.0,
    GlobalSettingNames.CRYPTO_ADDRESS_EXCLUDE_ENTITY_TAGS_REGEX: None,
}

# The three maximums that always carry a value: a stored/missing null resolves to the default.
ALWAYS_DEFAULTED_SETTINGS = (
    GlobalSettingNames.CRYPTO_ADDRESS_MAX_PLAYERS_TO_PUBLISH,
    GlobalSettingNames.CRYPTO_ADDRESS_MAX_TRANSACTIONS_TO_PUBLISH,
    GlobalSettingNames.CRYPTO_ADDRESS_MAX_BALANCE_EUR_TO_PUBLISH,
)

CUSTOM_SEGMENTATION_PRODUCT = "custom"

# Journal delivery outcomes.
ALERT_STATUS_DELIVERED = "delivered"
ALERT_STATUS_PARTIAL = "partial"
ALERT_STATUS_FAILED = "failed"
