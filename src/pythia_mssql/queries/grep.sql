-- Purpose: the modules of a schema whose definition holds a text; the
--          lines that hold it are picked out by the caller
-- Binds:   %(s)s schema, %(p)s LIKE pattern built from the text (escaped)
-- Returns: UNIT, TYPE, DEFINITION
select o.name       as unit,
       case o.type when 'U' then 'TABLE'
                   when 'V' then 'VIEW'
                   when 'P' then 'PROCEDURE'
                   when 'FN' then 'FUNCTION'
                   when 'IF' then 'FUNCTION'
                   when 'TF' then 'FUNCTION'
                   when 'TR' then 'TRIGGER'
                   when 'SO' then 'SEQUENCE'
                   when 'SN' then 'SYNONYM' end as type,
       m.definition as definition
  from sys.sql_modules m
  join sys.objects o on o.object_id = m.object_id
  join sys.schemas s on s.schema_id = o.schema_id
 where s.name = %(s)s
   and m.definition like %(p)s escape '\'
 order by o.name
