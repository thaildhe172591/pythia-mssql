-- Purpose: back to the transaction core owns, after the statement: commits
--          every inner level, which commits nothing — never the outermost,
--          which only core commits, after an approval
-- Binds:   none
-- Returns: nothing
while @@trancount > 1 commit transaction;
