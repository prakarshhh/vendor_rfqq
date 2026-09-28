"""Manual seed command:  python -m backend.seed
(The server also seeds automatically on startup.)"""
from . import db

if __name__ == "__main__":
    db.init_db()
    n = db.seed_rfqs()
    print(f"Seeded {n} RFQs into {db.DB_PATH}")
