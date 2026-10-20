-- Purpose: the primary key and unique constraints of a table, one row per
--          key column in key order
-- Binds:   %(objid)s the table's object_id
-- Returns: CONSTRAINT_NAME, KIND, INDEX_TYPE, COLUMN_NAME, KEY_ORDINAL, IS_DESCENDING
select quotename(kc.name)        as constraint_name,
       kc.type                   as kind,
       i.type_desc               as index_type,
       quotename(c.name)         as column_name,
       ic.key_ordinal            as key_ordinal,
       ic.is_descending_key      as is_descending
  from sys.key_constraints kc
  join sys.indexes i on i.object_id = kc.parent_object_id and i.index_id = kc.unique_index_id
  join sys.index_columns ic on ic.object_id = i.object_id and ic.index_id = i.index_id
  join sys.columns c on c.object_id = ic.object_id and c.column_id = ic.column_id
 where kc.parent_object_id = %(objid)s
 order by case kc.type when 'PK' then 0 else 1 end, kc.name, ic.key_ordinal
