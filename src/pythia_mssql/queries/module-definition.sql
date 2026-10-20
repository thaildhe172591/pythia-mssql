-- Purpose: one module's definition as it stands, and whether the module
--          exists at all (a NULL definition with an object_id is encrypted,
--          or unreadable to this login)
-- Binds:   %(q)s the module's bracket-quoted, schema-qualified name
-- Returns: OBJID, DEFINITION
select object_id(%(q)s)                    as objid,
       object_definition(object_id(%(q)s)) as definition
