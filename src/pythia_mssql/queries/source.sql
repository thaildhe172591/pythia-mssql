-- Purpose: the definition of one view, procedure, function or trigger, as
--          SQL Server keeps it (the text it was created with)
-- Binds:   %(s)s schema, %(n)s object name
-- Returns: UNIT, DEFINITION
select o.name       as unit,
       m.definition as definition
  from sys.sql_modules m
  join sys.objects o on o.object_id = m.object_id
  join sys.schemas s on s.schema_id = o.schema_id
 where s.name = %(s)s
   and o.name = %(n)s
