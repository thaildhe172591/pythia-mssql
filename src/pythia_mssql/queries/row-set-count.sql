-- Purpose: how many rows an UPDATE or DELETE touches, and a fingerprint of
--          them (any row joining, leaving or changing moves it). The caller
--          puts the statement's own table and predicate where the markers
--          are and runs the text with no binds
-- Binds:   none
-- Returns: ROW_COUNT, FINGERPRINT
select count(*)                                   as row_count,
       coalesce(checksum_agg(binary_checksum(*)), 0) as fingerprint
  from /*TARGET*/ where /*WHERE*/
