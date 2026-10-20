-- Purpose: the session a rehearsal runs in: an error must not end the open
--          transaction (XACT_ABORT OFF), and a lock is waited on for at most
--          five seconds
-- Binds:   none
-- Returns: nothing
set xact_abort off;
set lock_timeout 5000;
