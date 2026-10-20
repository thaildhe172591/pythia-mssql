-- Purpose: how much more this login can do than a change needs
-- Binds:   none
-- Returns: IS_SYSADMIN, IS_DB_OWNER, LOGIN_NAME
select is_srvrolemember('sysadmin') as is_sysadmin,
       is_member('db_owner')        as is_db_owner,
       suser_sname()                as login_name
