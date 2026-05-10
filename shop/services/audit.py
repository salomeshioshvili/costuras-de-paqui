"""Single audit-log helper. Every write that changes state should call log()."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User

from shop.models import AuditLog


def _serialize(value: Any) -> Any:
    """Make a value JSON-friendly for storing in `before`/`after`."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return repr(value)


def _serialize_dict(d: dict | None) -> dict:
    if not d:
        return {}
    return {k: _serialize(v) for k, v in d.items()}


def log(
    *,
    actor: User | None,
    action: str,
    target=None,
    before: dict | None = None,
    after: dict | None = None,
    message: str = '',
) -> AuditLog:
    target_type = ''
    target_id = None
    if target is not None:
        target_type = target._meta.model_name
        target_id = getattr(target, 'pk', None)
    return AuditLog.objects.create(
        actor=actor if isinstance(actor, User) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=_serialize_dict(before),
        after=_serialize_dict(after),
        message=message[:400],
    )


def for_target(target) -> list[AuditLog]:
    return list(
        AuditLog.objects.filter(
            target_type=target._meta.model_name,
            target_id=getattr(target, 'pk', None),
        )
    )
