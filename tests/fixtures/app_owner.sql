-- The live check's fixture. It drops and recreates two schemas: load it
-- into a disposable database only, never a shared one.
create schema app_owner;
GO
create schema reporting;
GO
create sequence app_owner.seq_order as bigint start with 1 increment by 1;
GO
create table app_owner.t_order (
    id bigint not null constraint df_t_order_id default (next value for app_owner.seq_order),
    status varchar(10) not null constraint df_t_order_status default ('DRAFT'),
    total numeric(12,2) not null constraint df_t_order_total default ((0)),
    created datetime2(3) not null constraint df_t_order_created default (sysutcdatetime()),
    constraint pk_t_order primary key clustered (id),
    constraint ck_t_order_status check (status in ('DRAFT', 'PAID'))
);
GO
create index ix_order_status on app_owner.t_order (status) include (total);
GO
exec sys.sp_addextendedproperty @name = N'MS_Description', @value = N'Customer orders',
    @level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', @level1name = N't_order';
GO
exec sys.sp_addextendedproperty @name = N'MS_Description', @value = N'DRAFT until paid',
    @level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', @level1name = N't_order',
    @level2type = N'COLUMN', @level2name = N'status';
GO
create table app_owner.t_order_line (
    id int identity(1,1) not null constraint pk_t_order_line primary key,
    order_id bigint not null,
    qty int not null,
    amount as (qty * 2) persisted,
    constraint fk_line_order foreign key (order_id) references app_owner.t_order (id) on delete cascade
);
GO
create table app_owner.t_order_audit (
    id int identity(1,1) not null constraint pk_t_order_audit primary key,
    order_id bigint not null,
    at datetime2 not null constraint df_audit_at default (sysutcdatetime())
);
GO
create view app_owner.v_order_summary as
select status, count(*) as n, sum(total) as total
  from app_owner.t_order
 group by status;
GO
create view reporting.v_paid as
select id, total from app_owner.t_order where status = 'PAID';
GO
create function app_owner.f_order_total(@id bigint) returns numeric(12,2) as
begin
    -- the total of one order
    return (select total from app_owner.t_order where id = @id);
end;
GO
create procedure app_owner.p_order_paid @id bigint as
begin
    set nocount on;
    update app_owner.t_order set status = 'PAID' where id = @id;
end;
GO
create procedure app_owner.p_order_count as
begin
    exec sp_executesql N'select count(*) from app_owner.t_order';
end;
GO
create trigger app_owner.trg_order_audit on app_owner.t_order after update as
begin
    set nocount on;
    insert into app_owner.t_order_audit (order_id) select id from inserted;
end;
GO
create procedure app_owner.p_broken as
select missing_col from app_owner.t_missing;
GO
insert into app_owner.t_order (status, total) values ('DRAFT', 10), ('DRAFT', 20), ('PAID', 30);
GO
