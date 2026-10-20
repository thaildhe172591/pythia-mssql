-- Purpose: every enabled trigger in the database, on a table or on the
--          database itself, with its text: what can fire inside a rehearsal
--          (a NULL definition is encrypted, or unreadable to this login)
-- Binds:   none
-- Returns: SCHEMA_NAME, TRIGGER_NAME, DEFINITION
select coalesce(object_schema_name(t.parent_id), '') as schema_name,
       t.name                                        as trigger_name,
       m.definition                                  as definition
  from sys.triggers t
  left join sys.sql_modules m on m.object_id = t.object_id
 where t.is_disabled = 0
 order by t.name
