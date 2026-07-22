"""
User Preferences Service (PRD V2.2/2.3 Feature 2 & 3).

Saves and retrieves briefing email preferences.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.models.contracts import UserPreferences

logger = logging.getLogger("voxquery.services.preferences")

# In-memory preferences fallback store
_PREFERENCES_DB: dict[UUID, UserPreferences] = {}


async def get_user_preferences(user_id: UUID) -> UserPreferences:
    """
    Get user preferences.
    """
    if user_id not in _PREFERENCES_DB:
        _PREFERENCES_DB[user_id] = UserPreferences(
            user_id=user_id,
            email_briefing_enabled=False,
            email=None,
            delivery_time="08:00",
        )
    return _PREFERENCES_DB[user_id]


async def update_user_preferences(
    user_id: UUID,
    email_briefing_enabled: bool,
    email: str | None,
    delivery_time: str,
) -> UserPreferences:
    """
    Update user preferences.
    """
    prefs = UserPreferences(
        user_id=user_id,
        email_briefing_enabled=email_briefing_enabled,
        email=email,
        delivery_time=delivery_time,
    )
    _PREFERENCES_DB[user_id] = prefs
    return prefs
