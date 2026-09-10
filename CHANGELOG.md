## v0.2.0 (2026-09-10)

### Feat

- **#14**: switch SQLFileSystem to async SQLAlchemy

### Refactor

- **#14**: normalize SQLFileSystem paths to relative form
- **#14**: remove unnecessary begin() wrappers
- **#14**: keep a long-lived connection on SQLFileSystem

## v0.1.1 (2026-08-28)

### Fix

- **#11**: skip empty release bumps

## v0.1.0 (2026-08-27)

### Feat

- **#5**: add Postgres test backend via testcontainers
- **#4**: implement SQLFileSystem core path CRUD
- **#3**: add SQLite test harness and path CRUD behaviour tests
- **#1**: add src and tests packages
- **#1**: add prek config
- **#1**: add core and dev deps. configure tests, ruff and build backend
- **#1**: update README.md

### Fix

- **#5**: drop JSONB coercion and simplify test backend fixtures

### Refactor

- **#4**: apply review feedback on SQLFileSystem core
- **#3**: register sql protocol explicitly on the client
