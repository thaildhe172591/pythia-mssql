-- Purpose: the first rows an UPDATE or DELETE touches, for the preview —
--          one more than shown, so a cut is announced
-- Binds:   none
-- Returns: every column of the table
select top (11) * from /*TARGET*/ where /*WHERE*/
