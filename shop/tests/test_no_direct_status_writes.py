"""Grep guard: views must not write `.status =` directly. The workflow engine owns it.

If you legitimately need to skip the engine for a special reason, exempt that line
explicitly via the ALLOWLIST below.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

VIEWS_PATH = Path(__file__).resolve().parent.parent / 'views.py'
PORTAL_INTAKE_PATH = Path(__file__).resolve().parent.parent / 'services' / 'intake.py'

DIRECT_STATUS_RE = re.compile(r'\.status\s*=\s*(?![=])', re.MULTILINE)
PAYMENT_STATUS_RE = re.compile(r'\.payment_status\s*=\s*(?![=])')

# Lines that may legitimately set status outside the workflow:
# - portal/customer self-booking creates a brand-new order with status='received'
#   directly (no transition required, since it's the initial save).
# - convert_lead creates a brand-new order with status='received' directly.
# - lead.status (model has its own lifecycle, not state-machine governed).
# - update_fields lists, validators that only read status, etc.
ALLOWED_PATTERNS = [
    r"\.status\s*=\s*'received'",          # initial booking creates an order at 'received'
    r"\.payment_status\s*=\s*['\"]unpaid['\"]",  # initial booking creates 'unpaid'
    r'lead\.status =',                     # Lead has its own non-state-machine lifecycle
    r"\.assignment_status\s*=\s*",         # TaskAssignment is not state-machine governed
    r"defaults={'.*?'.*?'status'",          # get_or_create defaults dict
    r"'status'\s*:\s*['\"](received|unpaid)['\"]",
    r"item\.delivered = 'delivered'",      # cascade-only fallback in workflow
]

ALLOWED_RE = re.compile('|'.join(ALLOWED_PATTERNS))


class NoDirectStatusWritesTest(SimpleTestCase):
    def test_views_use_workflow_for_status(self):
        text = VIEWS_PATH.read_text(encoding='utf-8')
        violations = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if DIRECT_STATUS_RE.search(line) or PAYMENT_STATUS_RE.search(line):
                if ALLOWED_RE.search(line):
                    continue
                violations.append(f'views.py:{line_no}: {stripped}')
        self.assertFalse(
            violations,
            'Direct status writes are forbidden in views.py — go through workflow.transition. '
            'Offending lines:\n  ' + '\n  '.join(violations),
        )
