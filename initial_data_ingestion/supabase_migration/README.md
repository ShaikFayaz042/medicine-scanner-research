# Supabase Migration

This folder replaces the Supabase ingestion tables with the corrected local staging snapshot.

## Safety

- The script validates the staging CSVs first.
- It refuses to delete data unless `--yes` is supplied.
- Table deletion and reload are transactional. A load failure rolls back the replacement.
- Credentials are read from environment variables or the existing project `.env` files. Do not add credentials to this folder.

## Dry run

From the repository root:

```powershell
.\.venv\Scripts\python.exe initial_data_ingestion\supabase_migration\migrate_local_to_supabase.py --dry-run
```

## Replace Supabase data

```powershell
.\.venv\Scripts\python.exe initial_data_ingestion\supabase_migration\migrate_local_to_supabase.py --yes
```

The default input is:

```text
initial_data_ingestion/09_normalization/01_staging/corrected_aggregate
```

Use another validated staging directory with `--staging <path>`.
