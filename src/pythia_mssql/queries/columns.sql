-- Purpose: the columns of one table or view, for `cols`
-- Binds:   %(objid)s the object's object_id (from resolve.sql)
-- Returns: POSITION, COLUMN_NAME, DATA_TYPE, NULLABLE, COLUMN_DEFAULT, COMMENT
select c.column_id                                   as position,
       c.name                                        as column_name,
       case when t.name in ('varchar', 'char', 'varbinary', 'binary')
            then t.name + '(' + case when c.max_length = -1 then 'max'
                                     else cast(c.max_length as varchar(10)) end + ')'
            when t.name in ('nvarchar', 'nchar')
            then t.name + '(' + case when c.max_length = -1 then 'max'
                                     else cast(c.max_length / 2 as varchar(10)) end + ')'
            when t.name in ('decimal', 'numeric')
            then t.name + '(' + cast(c.precision as varchar(10)) + ','
                        + cast(c.scale as varchar(10)) + ')'
            when t.name in ('datetime2', 'time', 'datetimeoffset')
            then t.name + '(' + cast(c.scale as varchar(10)) + ')'
            else t.name end as data_type,
       case when c.is_nullable = 1 then 'YES' else 'NO' end as nullable,
       coalesce(object_definition(c.default_object_id),
                case when c.is_identity = 1 then 'IDENTITY' end,
                cc.definition)                       as column_default,
       cast(ep.value as nvarchar(4000))              as comment
  from sys.columns c
  join sys.types t on t.user_type_id = c.user_type_id
  left join sys.computed_columns cc
         on cc.object_id = c.object_id and cc.column_id = c.column_id
  left join sys.extended_properties ep
         on ep.class = 1 and ep.major_id = c.object_id
        and ep.minor_id = c.column_id and ep.name = 'MS_Description'
 where c.object_id = %(objid)s
 order by c.column_id
