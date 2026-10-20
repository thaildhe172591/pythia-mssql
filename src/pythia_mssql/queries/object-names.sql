-- Purpose: objects whose name matches a LIKE pattern, for `ls`
-- Binds:   %(s)s schema, %(p)s LIKE pattern, %(n)s how many rows at most
-- Returns: NAME, TYPE, CREATED, MODIFIED
select top (%(n)s)
       o.name        as name,
       case o.type when 'U' then 'TABLE'
                   when 'V' then 'VIEW'
                   when 'P' then 'PROCEDURE'
                   when 'FN' then 'FUNCTION'
                   when 'IF' then 'FUNCTION'
                   when 'TF' then 'FUNCTION'
                   when 'TR' then 'TRIGGER'
                   when 'SO' then 'SEQUENCE'
                   when 'SN' then 'SYNONYM' end as type,
       o.create_date as created,
       o.modify_date as modified
  from sys.objects o
  join sys.schemas s on s.schema_id = o.schema_id
 where s.name = %(s)s
   and o.name like %(p)s
   and o.is_ms_shipped = 0
   and o.type in ('U', 'V', 'P', 'FN', 'IF', 'TF', 'TR', 'SO', 'SN')
 order by o.name
