"""Exercise the actual embedded workflow client, with no network or credentials."""
import io
import json
import os
from pathlib import Path
import textwrap
import unittest
from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

workflow = Path(__file__).resolve().parents[2] / '.github/workflows/poi-board-reconciliation.yml'
source = workflow.read_text().split('# BEGIN VERIFIED BOARD CHECK\n', 1)[1].split('          # END VERIFIED BOARD CHECK', 1)[0]
namespace = {'__name__': 'workflow_test'}
exec(compile(textwrap.dedent(source), str(workflow), 'exec'), namespace)

class Response(io.StringIO):
    status = 200

def completed():
    local = datetime.now(timezone.utc).astimezone(ZoneInfo('America/Chicago'))
    hours = [h for h in (9, 12, 16, 20) if h <= local.hour]
    day = local.date() if hours else local.date() - timedelta(days=1)
    slot = datetime.combine(day, time(hours[-1] if hours else 20), local.tzinfo)
    return {'reason': 'completed', 'last_error': None, 'slot_at': slot.isoformat()}

class WorkflowCheckTests(unittest.TestCase):
    def invoke(self, body, status=200):
        calls = []
        def request(req, timeout):
            calls.append(req)
            self.assertEqual(timeout, 180)
            self.assertEqual(req.full_url, 'https://principal-oi-api.onrender.com/api/status-board/reconciliation-check')
            response = Response(json.dumps(body)); response.status = status
            return response
        with patch.dict(os.environ, API_BASE_URL='https://principal-oi-api.onrender.com', BOARD_RECONCILIATION_SECRET='synthetic-only'), patch.dict(namespace, urlopen=request):
            namespace['check_board']()
        self.assertEqual(len(calls), 1)

    def test_completed_current_slot(self):
        self.invoke(completed())

    def test_unconfirmed_reasons_never_succeed(self):
        for reason in ['failed', 'busy_or_retry_wait', 'disabled', None]:
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                self.invoke({**completed(), 'reason': reason})

    def test_errors_and_http_failure_never_succeed(self):
        for error in ['identity_error', '', False]:
            with self.subTest(error=error), self.assertRaises(ValueError):
                self.invoke({**completed(), 'last_error': error})
        with self.assertRaises(ValueError): self.invoke(completed(), 503)

    def test_stale_future_naive_and_invalid_slot_never_succeed(self):
        for slot in ['2000-01-01T00:00:00Z', '2999-01-01T00:00:00Z', '2026-10-19T09:00:00', 'not-a-date', None]:
            with self.subTest(slot=slot), self.assertRaises((ValueError, AttributeError)):
                self.invoke({**completed(), 'slot_at': slot})

    def test_malformed_envelopes_never_succeed(self):
        for body in [None, [], {}, {'reason': 'completed'}]:
            with self.subTest(body=body), self.assertRaises((ValueError, KeyError)):
                self.invoke(body)

    def test_transport_error_not_retried_or_hidden(self):
        calls = []
        def fail(*args, **kwargs):
            calls.append(1); raise TimeoutError()
        with patch.dict(os.environ, API_BASE_URL='https://principal-oi-api.onrender.com', BOARD_RECONCILIATION_SECRET='synthetic-only'), patch.dict(namespace, urlopen=fail):
            with self.assertRaises(TimeoutError): namespace['check_board']()
        self.assertEqual(calls, [1])

if __name__ == '__main__': unittest.main()
