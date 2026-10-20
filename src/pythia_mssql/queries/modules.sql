-- Purpose: the modules `errors` binds — one, or every one in a schema —
--          and whether each holds dynamic SQL, which nothing can bind before
--          it runs
-- Binds:   %(s)s schema, %(n)s one object's name, or NULL for all
-- Returns: NAME, TYPE, QUALIFIED_NAME, HAS_DYNAMIC_SQL
select o.name as name,
       case o.type when 'U' then 'TABLE'
                   when 'V' then 'VIEW'
                   when 'P' then 'PROCEDURE'
                   when 'FN' then 'FUNCTION'
                   when 'IF' then 'FUNCTION'
                   when 'TF' then 'FUNCTION'
                   when 'TR' then 'TRIGGER'
                   when 'SO' then 'SEQUENCE'
                   when 'SN' then 'SYNONYM' end as type,
       quotename(s.name) + '.' + quotename(o.name) as qualified_name,
       case when m.definition like '%%sp_executesql%%'
              or m.definition like '%%exec%%[(]%%@%%' then 1 else 0 end as has_dynamic_sql
  from sys.sql_modules m
  join sys.objects o on o.object_id = m.object_id
  join sys.schemas s on s.schema_id = o.schema_id
 where s.name = %(s)s
   and (%(n)s is null or o.name = %(n)s)
   and o.is_ms_shipped = 0
 order by o.name
