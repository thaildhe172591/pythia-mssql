-- Purpose: modules whose definition holds a name — a lead, not a proof: the
--          caller keeps whole-word matches only (dynamic SQL names objects
--          inside strings, where the catalog never looks)
-- Binds:   %(p)s LIKE pattern holding the name, %(objid)s the object itself
-- Returns: SCHEMA_NAME, NAME, TYPE, OBJID, DEFINITION
select s.name as schema_name, o.name as name,
       case o.type when 'U' then 'TABLE'
                   when 'V' then 'VIEW'
                   when 'P' then 'PROCEDURE'
                   when 'FN' then 'FUNCTION'
                   when 'IF' then 'FUNCTION'
                   when 'TF' then 'FUNCTION'
                   when 'TR' then 'TRIGGER'
                   when 'SO' then 'SEQUENCE'
                   when 'SN' then 'SYNONYM' end as type,
       o.object_id as objid, m.definition as definition
  from sys.sql_modules m
  join sys.objects o on o.object_id = m.object_id
  join sys.schemas s on s.schema_id = o.schema_id
 where m.definition like %(p)s escape '\'
   and o.object_id <> %(objid)s
   and o.is_ms_shipped = 0
