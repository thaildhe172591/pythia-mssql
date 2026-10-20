-- Purpose: the foreign keys of a table, one row per column pair in order
-- Binds:   %(objid)s the table's object_id
-- Returns: CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE, REFERENCED_COLUMN,
--          ON_DELETE, ON_UPDATE
select quotename(fk.name)                                       as constraint_name,
       quotename(pc.name)                                       as column_name,
       quotename(rs.name) + '.' + quotename(ro.name)            as referenced_table,
       quotename(rc.name)                                       as referenced_column,
       fk.delete_referential_action_desc                        as on_delete,
       fk.update_referential_action_desc                        as on_update
  from sys.foreign_keys fk
  join sys.foreign_key_columns fkc on fkc.constraint_object_id = fk.object_id
  join sys.columns pc on pc.object_id = fkc.parent_object_id and pc.column_id = fkc.parent_column_id
  join sys.objects ro on ro.object_id = fkc.referenced_object_id
  join sys.schemas rs on rs.schema_id = ro.schema_id
  join sys.columns rc on rc.object_id = fkc.referenced_object_id and rc.column_id = fkc.referenced_column_id
 where fk.parent_object_id = %(objid)s
 order by fk.name, fkc.constraint_column_id
