import os


# Never use a developer's configured database while importing server modules in tests.
os.environ["MEDICINE_DB_URI"] = (
    "postgresql+psycopg2://test:test@db.test-project.supabase.co:5432/test?sslmode=require"
)