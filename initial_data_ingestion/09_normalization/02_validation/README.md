# Validation

The validation entry point is the eight-test suite in `tests`:

```powershell
python -m tests.run_all
```

The suite writes isolated test outputs under `09_normalization/staging` and does not load the database.