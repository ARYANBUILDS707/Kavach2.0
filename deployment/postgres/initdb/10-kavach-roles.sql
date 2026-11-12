-- Development/test bootstrap (M2.1): runs once, on an empty data volume, as the image superuser.
-- Creates the three least-privilege roles from DATABASE.md and two disposable databases.
-- Table-level grants arrive with the schema migrations in M2.2.
\set ON_ERROR_STOP on

\getenv migrator_password KAVACH_DEV_MIGRATOR_PASSWORD
\getenv app_password KAVACH_DEV_APP_PASSWORD
\getenv retention_password KAVACH_DEV_RETENTION_PASSWORD

-- Migration owner: owns the databases and schema; no cluster-level privileges.
CREATE ROLE kavach_migrator WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'migrator_password';
-- Runtime and retention roles: connect and use the schema only; never own objects.
CREATE ROLE kavach_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    PASSWORD :'app_password';
CREATE ROLE kavach_retention WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    PASSWORD :'retention_password';

CREATE DATABASE kavach_dev OWNER kavach_migrator;
CREATE DATABASE kavach_test OWNER kavach_migrator;

\connect kavach_dev
REVOKE ALL ON DATABASE kavach_dev FROM PUBLIC;
GRANT CONNECT ON DATABASE kavach_dev TO kavach_app, kavach_retention;
ALTER SCHEMA public OWNER TO kavach_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO kavach_app, kavach_retention;

\connect kavach_test
REVOKE ALL ON DATABASE kavach_test FROM PUBLIC;
GRANT CONNECT ON DATABASE kavach_test TO kavach_app, kavach_retention;
ALTER SCHEMA public OWNER TO kavach_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO kavach_app, kavach_retention;
