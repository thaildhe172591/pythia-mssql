-- Purpose: the server's version, edition and the database this session is in
-- Binds:   none
-- Returns: VERSION, EDITION, DATABASE_NAME
select cast(serverproperty('ProductVersion') as nvarchar(128)) as version,
       cast(serverproperty('Edition') as nvarchar(128))        as edition,
       db_name()                                               as database_name
