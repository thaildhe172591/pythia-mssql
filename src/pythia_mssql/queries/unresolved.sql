-- Purpose: the names a module references that do not exist in this
--          database — what SQL Server's error 2020 leaves unsaid
-- Binds:   %(q)s the module's bracket-quoted, schema-qualified name
-- Returns: MISSING
select coalesce(d.referenced_schema_name + '.', '') + d.referenced_entity_name as missing
  from sys.sql_expression_dependencies d
 where d.referencing_id = object_id(%(q)s)
   and d.referenced_id is null
   and d.referenced_class = 1
   and d.referenced_database_name is null
   and d.is_caller_dependent = 0
 order by 1
