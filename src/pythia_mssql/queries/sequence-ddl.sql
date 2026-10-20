-- Purpose: what a CREATE SEQUENCE needs
-- Binds:   %(objid)s the sequence's object_id
-- Returns: QUALIFIED_NAME, DATA_TYPE, START_VALUE, INCREMENT, MINIMUM_VALUE,
--          MAXIMUM_VALUE, IS_CYCLING, CACHE_SIZE, IS_CACHED
select quotename(s.name) + '.' + quotename(sq.name) as qualified_name,
       type_name(sq.user_type_id)                   as data_type,
       cast(sq.start_value as nvarchar(40))         as start_value,
       cast(sq.increment as nvarchar(40))           as increment,
       cast(sq.minimum_value as nvarchar(40))       as minimum_value,
       cast(sq.maximum_value as nvarchar(40))       as maximum_value,
       sq.is_cycling                                as is_cycling,
       sq.cache_size                                as cache_size,
       sq.is_cached                                 as is_cached
  from sys.sequences sq
  join sys.schemas s on s.schema_id = sq.schema_id
 where sq.object_id = %(objid)s
