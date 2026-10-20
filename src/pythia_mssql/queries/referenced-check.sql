-- Purpose: bind one module's references now, the way SQL Server would run
--          it: a missing table or column raises its error (207, 208...)
--          without ending the open transaction
-- Binds:   %(q)s the module's bracket-quoted, schema-qualified name
-- Returns: REFERENCES
select count(*) as references_found
  from sys.dm_sql_referenced_entities(%(q)s, 'OBJECT')
