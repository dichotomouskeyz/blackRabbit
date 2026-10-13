"""INV-007 — create_session validation surfaces as structured 422 [integration].

Integration contract:
  Entry: FastAPI TestClient(app) — real app, route, dependency chain.
  Through: the create route and create_session validation must be exercised;
           create_session validation must NOT be mocked.
  Exit:  status 422; body {field, message, valid_choices?} naming the invalid
         field; valid_choices for compound/dose_unit equal
         VALID_COMPOUNDS/VALID_DOSE_UNITS.

Also covers /vocab (INV-007): compounds == VALID_COMPOUNDS,
dose_units == VALID_DOSE_UNITS.
"""

import pytest

from capture.session_init.constants import VALID_COMPOUNDS, VALID_DOSE_UNITS
from tests.api_tests.support import _INT_PARTICIPANT, _UNIT_VALID_COMPOUND


@pytest.mark.integration
def test_invalid_compound_returns_structured_422(client, override_tenant):
    # Tests INV-007 [integration]: invalid compound -> 422 {field, message, valid_choices}.
    # create_session validation is NOT mocked (real pre-DB ValueError surfaces).
    from tests.api_tests.support import _INT_SITE_A, _INT_SPONSOR_A

    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    body = {
        "compound": "definitely_not_a_real_compound",
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
    }
    resp = client.post("/sessions", json=body)
    assert resp.status_code == 422, f"expected structured 422, got {resp.status_code}"
    payload = resp.json()
    assert "field" in payload and "message" in payload, f"unstructured body: {payload}"
    assert payload["field"] == "compound"
    assert list(payload["valid_choices"]) == list(VALID_COMPOUNDS)


@pytest.mark.integration
def test_invalid_dose_unit_returns_structured_422(client, override_tenant):
    # Tests INV-007 [integration]: invalid dose unit -> 422 with VALID_DOSE_UNITS.
    from tests.api_tests.support import _INT_SITE_A, _INT_SPONSOR_A

    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
        "compound_dose": 25.0,
        "compound_dose_unit": "furlongs",
    }
    resp = client.post("/sessions", json=body)
    assert resp.status_code == 422
    payload = resp.json()
    assert payload["field"] in ("compound_dose_unit", "dose_unit")
    assert list(payload["valid_choices"]) == list(VALID_DOSE_UNITS)


@pytest.mark.integration
def test_valid_request_creates_session_row(client, override_tenant, cursor):
    # Tests INV-007 [integration]: a valid request creates a real DB row via the
    # real create_session (NOT mocked).
    from tests.api_tests.support import _INT_SITE_A, _INT_SPONSOR_A

    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
    }
    resp = client.post("/sessions", json=body)
    assert resp.status_code in (200, 201), f"valid create failed: {resp.status_code} {resp.text}"
    session_id = resp.json()["session_id"]
    cursor.execute(
        "SELECT compound, sponsor_id, site_id FROM sessions WHERE id = %s::uuid",
        (session_id,),
    )
    row = cursor.fetchone()
    assert row is not None, "create_session did not persist a sessions row"
    assert row[0] == _UNIT_VALID_COMPOUND
    # cleanup
    cursor.execute("DELETE FROM sessions WHERE id = %s::uuid", (session_id,))


def test_vocab_sources_from_session_init_sets(client):
    # Tests INV-007 [integration]: /vocab equals the canonical choice sets.
    resp = client.get("/vocab")
    assert resp.status_code == 200
    payload = resp.json()
    assert list(payload["compounds"]) == list(VALID_COMPOUNDS)
    assert list(payload["dose_units"]) == list(VALID_DOSE_UNITS)
