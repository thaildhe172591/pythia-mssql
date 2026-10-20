-- Purpose: one transaction level down for the statement, so a trigger's
--          single COMMIT ends only this level and commits nothing
-- Binds:   none
-- Returns: nothing
begin transaction;
