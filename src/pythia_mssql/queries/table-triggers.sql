-- Purpose: the definitions of a table's triggers
-- Binds:   %(objid)s the table's object_id
-- Returns: DEFINITION
select m.definition as definition
  from sys.triggers tr
  join sys.sql_modules m on m.object_id = tr.object_id
 where tr.parent_id = %(objid)s
 order by tr.name
