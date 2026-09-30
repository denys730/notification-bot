"""The reference catalogue of checker rows — what a freshly seeded brand starts with.

A production service would leave seeding to operators; the demo DOES seed these at startup for a
brand that has no rows (`SEED_ON_STARTUP`), because an empty demo shows nothing. Every row here satisfies its checker's `REQUIRED_CONFIG_KEYS` and bounds — the registry
test enforces that.
"""

from typing import Any

from constants import CheckerCodes

ALERT_CHANNEL = "#demo-alerts"
MONITORING_CHANNEL = "#demo-monitoring"


def default_rows(brand: str) -> list[dict[str, Any]]:
    brand = brand.upper()
    return [
        {
            "brand": brand,
            "checker_code": CheckerCodes.HEARTBEAT.value,
            "checker_name": "Heartbeat",
            "description": "Probes the demo service's own dependencies; failures go to the monitoring channel.",
            "channel": MONITORING_CHANNEL,
            "channels": [MONITORING_CHANNEL],
            "enabled": True,
            "frequency_minutes": 30,
            "cron": None,
            "max_instances": 1,
            "config": {},
            "segments": None,
            "regions": None,
        },
        {
            "brand": brand,
            "checker_code": CheckerCodes.THRESHOLD_BREACH.value,
            "checker_name": "Threshold Breach 5000 24h",
            "description": "An entity's successful amounts over a rolling day reach 5,000.",
            "channel": ALERT_CHANNEL,
            "channels": [ALERT_CHANNEL],
            "enabled": True,
            "frequency_minutes": 15,
            "cron": None,
            "max_instances": 1,
            "config": {
                "monitoring_window_hours": 24,
                "threshold": 5000,
                "event_kind": "inflow",
                "check_vip_users": True,
                "check_non_vip_users": True,
                "mentions": {},
            },
            "segments": None,
            "regions": None,
        },
        {
            "brand": brand,
            "checker_code": CheckerCodes.THRESHOLD_BREACH.value,
            "checker_name": "Threshold Breach 1000 1h Premium",
            "description": "A tighter rule for Premium entities: 1,000 within one hour. Disabled until the team confirms the channel.",
            "channel": ALERT_CHANNEL,
            "channels": [ALERT_CHANNEL, "#demo-vip"],
            "enabled": False,
            "frequency_minutes": 5,
            "cron": None,
            "max_instances": 1,
            "config": {
                "monitoring_window_hours": 1,
                "threshold": 1000,
                "event_kind": "inflow",
                "check_vip_users": True,
                "check_non_vip_users": False,
                "mentions": {},
            },
            "segments": ["Business__34"],
            "regions": None,
        },
        {
            "brand": brand,
            "checker_code": CheckerCodes.ACTIVITY_DROP.value,
            "checker_name": "Activity Drop 50% 30m",
            "description": "Event volume in the last 30 minutes is half of the same slot's 7-day average.",
            "channel": ALERT_CHANNEL,
            "channels": [ALERT_CHANNEL],
            "enabled": True,
            "frequency_minutes": 10,
            "cron": None,
            "max_instances": 1,
            "config": {"window_minutes": 30, "baseline_days": 7, "drop_percent": 50, "min_baseline_events": 20},
            "segments": None,
            "regions": None,
        },
        {
            "brand": brand,
            "checker_code": CheckerCodes.STATUS_STUCK.value,
            "checker_name": "Status Stuck 120m EU",
            "description": "An EU entity's latest event has been pending for more than two hours.",
            "channel": ALERT_CHANNEL,
            "channels": [ALERT_CHANNEL],
            "enabled": True,
            "frequency_minutes": 15,
            "cron": "*/15 * * * *",
            "max_instances": 1,
            "config": {"pending_minutes": 120, "pending_statuses": ["pending"], "cache_ttl_hours": 24},
            "segments": None,
            "regions": ["EU"],
        },
    ]
