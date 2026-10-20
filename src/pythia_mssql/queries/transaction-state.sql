-- Purpose: the session's transaction around a rehearsed statement: how deep
--          it is nested, and which transaction it is — a trigger that
--          commits or rolls back ends it, or swaps it for a new one
-- Binds:   none
-- Returns: TRANCOUNT, TXN
select @@trancount              as trancount,
       current_transaction_id() as txn
