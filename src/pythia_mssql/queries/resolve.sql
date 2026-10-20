-- Purpose: the object in a schema holding a name, as the catalog identifies
--          it, so the dependency walks start from an object_id
-- Binds:   %(s)s schema, %(n)s object name (brackets already removed)
-- Returns: OBJID, TYPE, LABEL, BARE_NAME
select o.object_id as objid,
       case o.type when 'U' then 'TABLE'
                   when 'V' then 'VIEW'
                   when 'P' then 'PROCEDURE'
                   when 'FN' then 'FUNCTION'
                   when 'IF' then 'FUNCTION'
                   when 'TF' then 'FUNCTION'
                   when 'TR' then 'TRIGGER'
                   when 'SO' then 'SEQUENCE'
                   when 'SN' then 'SYNONYM' end as type,
       o.name      as label,
       o.name      as bare_name
  from sys.objects o
  join sys.schemas s on s.schema_id = o.schema_id
 where s.name = %(s)s
   and o.name = %(n)s
   and o.is_ms_shipped = 0
   and o.type in ('U', 'V', 'P', 'FN', 'IF', 'TF', 'TR', 'SO', 'SN')
