-- Purpose: the MS_Description on a table, a view or one of their columns,
--          as it stands; no row when there is none
-- Binds:   %(s)s schema, %(t)s table or view, %(c)s column, or NULL
-- Returns: COMMENT
select cast(ep.value as nvarchar(4000)) as comment
  from sys.extended_properties ep
  join sys.objects o on o.object_id = ep.major_id
  join sys.schemas s on s.schema_id = o.schema_id
 where ep.class = 1
   and ep.name = 'MS_Description'
   and s.name = %(s)s
   and o.name = %(t)s
   and ep.minor_id = coalesce((select c.column_id from sys.columns c
                                where c.object_id = o.object_id and c.name = %(c)s), 0)
   and (%(c)s is null or ep.minor_id <> 0)
