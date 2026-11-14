from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from sqlalchemy import text

from database import engine, Base
import models
from routers import campaigns, donations, donors, receipts, utilizations, admins, auth, campaign_updates
from routers import ai, ledger as ledger_router, milestones, payments
from services import ledger
from seed_campaigns import seed_if_empty

# Auto-create tables on startup
Base.metadata.create_all(bind=engine)

# Lightweight schema sync: add columns that were introduced after a table
# was first created. Avoids "UndefinedColumn" errors without needing Alembic.
_SCHEMA_SYNC_STATEMENTS = [
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS start_date TIMESTAMP",
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS end_date TIMESTAMP",
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS close_reason VARCHAR",
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS daily_donor_limit FLOAT",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS donor_id INTEGER REFERENCES donors(id)",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS payment_method VARCHAR",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS transaction_id VARCHAR",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'completed'",
    "ALTER TABLE organizers ADD COLUMN IF NOT EXISTS phone VARCHAR",
    "ALTER TABLE donors ADD COLUMN IF NOT EXISTS phone VARCHAR",
    # Blockchain + AI upgrade
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS risk_score FLOAT",
    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS risk_flags JSON",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS payment_order_id VARCHAR",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS risk_score FLOAT",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS risk_flags JSON",
    "ALTER TABLE donations ADD COLUMN IF NOT EXISTS ledger_hash VARCHAR",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS milestone_id INTEGER REFERENCES milestones(id)",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS vendor_name VARCHAR",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS vendor_gstin VARCHAR",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS invoice_number VARCHAR",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS invoice_date VARCHAR",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS invoice_hash VARCHAR",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS ocr_total FLOAT",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS ocr_confidence FLOAT",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS risk_score FLOAT",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS risk_flags JSON",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'recorded'",
    "ALTER TABLE utilizations ADD COLUMN IF NOT EXISTS ledger_hash VARCHAR",
    "CREATE INDEX IF NOT EXISTS ix_utilizations_invoice_hash ON utilizations (invoice_hash)",
    "CREATE INDEX IF NOT EXISTS ix_donations_payment_order_id ON donations (payment_order_id)",
]
try:
    with engine.begin() as _conn:
        for _stmt in _SCHEMA_SYNC_STATEMENTS:
            _conn.execute(text(_stmt))
except Exception as _e:
    print(f"[schema-sync] warning: {_e}")

seed_if_empty()

# Put any pre-existing donations / expenses on the ledger (idempotent).
try:
    from database import SessionLocal
    _db = SessionLocal()
    try:
        _n = ledger.backfill(_db)
        if _n:
            print(f"[ledger] backfilled {_n} historical records onto the chain")
    finally:
        _db.close()
except Exception as _e:
    print(f"[ledger] backfill warning: {_e}")

app = FastAPI(
    title="TransFund API",
    version="2.0.0",
    description="Blockchain and AI-powered transparent crowdfunding and fund utilization management.",
)

# Allow Next.js dev server (comma-separated list in CORS_ORIGINS to override)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded campaign images
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

app.include_router(campaigns.router)
app.include_router(donations.router)
app.include_router(donors.router)
app.include_router(receipts.router)
app.include_router(utilizations.router)
app.include_router(admins.router)
app.include_router(auth.router)
app.include_router(campaign_updates.router)
app.include_router(milestones.router)
app.include_router(payments.router)
app.include_router(ledger_router.router)
app.include_router(ai.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "TransFund API is running",
        "payments": payments.provider(),
        "chain_anchoring": "enabled" if __import__("services.chain_anchor", fromlist=["status"]).status()["enabled"] else "disabled",
    }
