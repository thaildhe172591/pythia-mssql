-- Purpose: what one object depends on, as SQL Server records it: what its
--          code references (in another database too, by name), the table a
--          trigger is on, the tables a table's foreign keys point at
-- Binds:   %(objid)s the object's object_id
-- Returns: SCHEMA_NAME, NAME, TYPE, OBJID
select distinct
       coalesce(rs.name, d.referenced_schema_name, '?') as schema_name,
       case when d.referenced_database_name is not null
            then d.referenced_database_name + '..' + d.referenced_entity_name
            else coalesce(ro.name, d.referenced_entity_name) end as name,
       case when ro.object_id is null then 'UNRESOLVED'
            else case ro.type when 'U' then 'TABLE' when 'V' then 'VIEW'
                              when 'P' then 'PROCEDURE' when 'FN' then 'FUNCTION'
                              when 'IF' then 'FUNCTION' when 'TF' then 'FUNCTION'
                              when 'TR' then 'TRIGGER' when 'SO' then 'SEQUENCE'
                              when 'SN' then 'SYNONYM' else ro.type_desc end end as type,
       ro.object_id as objid
  from sys.sql_expression_dependencies d
  left join sys.objects ro on ro.object_id = d.referenced_id
  left join sys.schemas rs on rs.schema_id = ro.schema_id
 where d.referencing_id = %(objid)s
   and d.referenced_class = 1
union
select s.name, o.name, 'TABLE', o.object_id
  from sys.objects t
  join sys.objects o on o.object_id = t.parent_object_id
  join sys.schemas s on s.schema_id = o.schema_id
 where t.object_id = %(objid)s
   and t.type = 'TR'
union
select s.name, o.name, 'TABLE', o.object_id
  from sys.foreign_keys fk
  join sys.objects o on o.object_id = fk.referenced_object_id
  join sys.schemas s on s.schema_id = o.schema_id
 where fk.parent_object_id = %(objid)s
   and fk.referenced_object_id <> %(objid)s
 order by 1, 2
