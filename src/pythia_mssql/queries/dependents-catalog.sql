-- Purpose: what depends on one object, as SQL Server records it: modules
--          that reference it (resolved, or by name when it did not exist
--          yet), tables whose check or default constraints use it, triggers
--          on a table, tables whose foreign keys point at it
-- Binds:   %(objid)s the object's object_id, %(s)s its schema, %(n)s its name
-- Returns: SCHEMA_NAME, NAME, TYPE, OBJID
select distinct s.name as schema_name, t.name as name,
       case t.type when 'U' then 'TABLE'
                   when 'V' then 'VIEW'
                   when 'P' then 'PROCEDURE'
                   when 'FN' then 'FUNCTION'
                   when 'IF' then 'FUNCTION'
                   when 'TF' then 'FUNCTION'
                   when 'TR' then 'TRIGGER'
                   when 'SO' then 'SEQUENCE'
                   when 'SN' then 'SYNONYM' end as type,
       t.object_id as objid
  from sys.sql_expression_dependencies d
  join sys.objects o on o.object_id = d.referencing_id
  -- a check or default constraint counts as the table it is on
  join sys.objects t on t.object_id = case when o.type in ('C', 'D')
                                           then o.parent_object_id
                                           else o.object_id end
  join sys.schemas s on s.schema_id = t.schema_id
 where d.referencing_class = 1
   and (d.referenced_id = %(objid)s
        or (d.referenced_id is null
            and d.referenced_database_name is null
            and d.referenced_entity_name = %(n)s
            and coalesce(d.referenced_schema_name, s.name) = %(s)s))
   and t.object_id <> %(objid)s
union
select s.name, o.name, 'TRIGGER', o.object_id
  from sys.objects o
  join sys.schemas s on s.schema_id = o.schema_id
 where o.parent_object_id = %(objid)s
   and o.type = 'TR'
union
select s.name, o.name, 'TABLE', o.object_id
  from sys.foreign_keys fk
  join sys.objects o on o.object_id = fk.parent_object_id
  join sys.schemas s on s.schema_id = o.schema_id
 where fk.referenced_object_id = %(objid)s
   and fk.parent_object_id <> %(objid)s
 order by 1, 2
