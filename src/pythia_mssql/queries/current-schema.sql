-- Purpose: where an unqualified name lands: this user's default schema
-- Binds:   none
-- Returns: CURRENT_SCHEMA
select schema_name() as current_schema
