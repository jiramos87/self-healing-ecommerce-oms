-- duplicate_of links a duplicate-delivery incident to the ORIGINAL ORDER row
-- (the PRD's "linked to the original delivery"), not to another incident.

ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_duplicate_of_fkey;
ALTER TABLE incidents
    ADD CONSTRAINT incidents_duplicate_of_fkey
    FOREIGN KEY (duplicate_of) REFERENCES orders (id);
