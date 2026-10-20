-- Purpose: the indexes of a table that no key constraint creates, one row
--          per column (key columns in order, then included ones)
-- Binds:   %(objid)s the table's object_id
-- Returns: INDEX_NAME, IS_UNIQUE, INDEX_TYPE, FILTER, COLUMN_NAME, IS_INCLUDED,
--          IS_DESCENDING
select quotename(i.name)          as index_name,
       i.is_unique                as is_unique,
       i.type_desc                as index_type,
       i.filter_definition        as filter,
       quotename(c.name)          as column_name,
       ic.is_included_column      as is_included,
       ic.is_descending_key       as is_descending
  from sys.indexes i
  join sys.index_columns ic on ic.object_id = i.object_id and ic.index_id = i.index_id
  join sys.columns c on c.object_id = ic.object_id and c.column_id = ic.column_id
 where i.object_id = %(objid)s
   and i.is_primary_key = 0
   and i.is_unique_constraint = 0
   and i.type in (1, 2)
 order by i.name, ic.is_included_column, ic.key_ordinal, ic.index_column_id
