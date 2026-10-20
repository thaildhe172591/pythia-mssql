-- Purpose: the check constraints of a table
-- Binds:   %(objid)s the table's object_id
-- Returns: CONSTRAINT_NAME, DEFINITION
select quotename(name) as constraint_name,
       definition      as definition
  from sys.check_constraints
 where parent_object_id = %(objid)s
 order by name
