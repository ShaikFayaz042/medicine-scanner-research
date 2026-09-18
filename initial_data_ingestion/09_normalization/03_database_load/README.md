# Database Load

Database loading is implemented by `shared.load_db` and consumes validated CSV output under `09_normalization/staging`.

The database-load structure test is included in the validation suite. Production loads should use an explicitly selected staging directory and database URI.