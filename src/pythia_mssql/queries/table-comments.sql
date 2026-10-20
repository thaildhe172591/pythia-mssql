-- Purpose: the MS_Description of a table and of its columns, the comment
--          SQL Server tools read
-- Binds:   %(objid)s the table's object_id
-- Returns: SCHEMA_NAME, TABLE_NAME, COLUMN_NAME, COMMENT
select s.name                           as schema_name,
       o.name                           as table_name,
       c.name                           as column_name,
       cast(ep.value as nvarchar(4000)) as comment
  from sys.extended_properties ep
  join sys.objects o on o.object_id = ep.major_id
  join sys.schemas s on s.schema_id = o.schema_id
  left join sys.columns c on c.object_id = ep.major_id and c.column_id = ep.minor_id
 where ep.class = 1
   and ep.major_id = %(objid)s
   and ep.name = 'MS_Description'
 order by ep.minor_id
