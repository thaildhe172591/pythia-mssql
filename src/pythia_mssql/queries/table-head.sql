-- Purpose: a table's qualified, bracket-quoted name, for its DDL
-- Binds:   %(objid)s the table's object_id
-- Returns: QUALIFIED_NAME
select quotename(s.name) + '.' + quotename(o.name) as qualified_name
  from sys.objects o
  join sys.schemas s on s.schema_id = o.schema_id
 where o.object_id = %(objid)s
