-- Purpose: each column of a table as its CREATE TABLE needs it
-- Binds:   %(objid)s the table's object_id
-- Returns: COLUMN_NAME, DATA_TYPE, IS_NULLABLE, DEFAULT_NAME, DEFAULT_DEFINITION,
--          IS_IDENTITY, SEED, INCREMENT, COMPUTED, IS_PERSISTED, COLLATION
select quotename(c.name)                              as column_name,
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
       c.is_nullable                                  as is_nullable,
       d.name                                         as default_name,
       d.definition                                   as default_definition,
       c.is_identity                                  as is_identity,
       cast(ic.seed_value as nvarchar(40))            as seed,
       cast(ic.increment_value as nvarchar(40))       as increment,
       cc.definition                                  as computed,
       cc.is_persisted                                as is_persisted,
       case when c.collation_name <> convert(sysname,
                 databasepropertyex(db_name(), 'Collation'))
            then c.collation_name end                 as collation
  from sys.columns c
  join sys.types t on t.user_type_id = c.user_type_id
  left join sys.default_constraints d on d.object_id = c.default_object_id
  left join sys.identity_columns ic
         on ic.object_id = c.object_id and ic.column_id = c.column_id
  left join sys.computed_columns cc
         on cc.object_id = c.object_id and cc.column_id = c.column_id
 where c.object_id = %(objid)s
 order by c.column_id
