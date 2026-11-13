# Schema versions

Version 2 adds `agreements.labels` (framework labels, JSON), `agreements.rel_path` (imported folder path) and a `settings` table (alert settings). `migrate()` adds the two columns to an existing version 1 database in place.

## Version 1

Run `python -m scripts.migrate` to create the initial schema idempotently. Startup also runs this step. Models cover agreements, jobs, audit metadata, spreadsheet batches and schema version.

This is an initial schema migration, not a complete schema-upgrade framework. Subsequent releases must introduce explicit forward migration scripts and verify backups/upgrade behavior. Never run application tests on an existing database: tests recreate tables.
