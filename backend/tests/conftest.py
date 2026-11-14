"""
Integration tests run against a throwaway Postgres database.
    TEST_DATABASE_URL=postgresql://postgres:1234@localhost:5432/transfund_test pytest backend/tests
"""
import os
import sys

import pytest

TEST_URL = os.getenv("TEST_DATABASE_URL", "postgresql://postgres:1234@localhost:5432/transfund_test")
os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("LEDGER_DIFFICULTY", "2")
for k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET",
          "CHAIN_RPC_URL", "CHAIN_PRIVATE_KEY", "CHAIN_CONTRACT_ADDRESS"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _recreate_db():
    import psycopg2
    from urllib.parse import urlparse

    u = urlparse(TEST_URL)
    conn = psycopg2.connect(host=u.hostname, port=u.port or 5432, user=u.username, password=u.password, dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    name = u.path.lstrip("/")
    cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    cur.execute(f'CREATE DATABASE "{name}"')
    conn.close()


@pytest.fixture(scope="session")
def client():
    try:
        _recreate_db()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Postgres not available: {e}")
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def campaign(client):
    import uuid
    org = f"org-{uuid.uuid4().hex[:8]}@ngo.in"
    client.post("/auth/register", json={"role": "organizer", "name": "Test Org", "email": org, "password": "x"})
    r = client.post("/campaigns/", data={
        "title": "Clean water for Barmer", "category": "Community", "goal_amount": "50000", "organizer_email": org,
        "description": "Installing community water filters in five villages; every invoice is published here.",
        "milestones": '[{"title":"Filters","amount":20000},{"title":"Maintenance","amount":30000}]',
    })
    assert r.status_code == 200, r.text
    return {**r.json(), "org": org}
