-- Create the 7 demo logins with the passwords your team agreed on.
-- Same accounts and roles as sessions/09_create_demo_users.sql, but with
-- known passwords instead of random ones. Run as root, AFTER 05_roles.sql.
-- Replace every 'CHANGE_ME_...' with the real password, and do not commit
-- the filled-in copy.

CREATE USER IF NOT EXISTS 'admin'@'localhost'     IDENTIFIED BY 'CHANGE_ME_admin';
CREATE USER IF NOT EXISTS 'app'@'localhost'       IDENTIFIED BY 'CHANGE_ME_app';
CREATE USER IF NOT EXISTS 'p_5'@'localhost'       IDENTIFIED BY 'CHANGE_ME_p5';
CREATE USER IF NOT EXISTS 'p_23'@'localhost'      IDENTIFIED BY 'CHANGE_ME_p23';
CREATE USER IF NOT EXISTS 'detection'@'localhost' IDENTIFIED BY 'CHANGE_ME_detection';
CREATE USER IF NOT EXISTS 'ledger'@'localhost'    IDENTIFIED BY 'CHANGE_ME_ledger';
CREATE USER IF NOT EXISTS 'readonly'@'localhost'  IDENTIFIED BY 'CHANGE_ME_readonly';

GRANT 'role_admin'@'%'        TO 'admin'@'localhost';
GRANT 'role_app'@'%'          TO 'app'@'localhost';
GRANT 'role_manufacturer'@'%' TO 'p_5'@'localhost';
GRANT 'role_retailer'@'%'     TO 'p_23'@'localhost';
GRANT 'role_detection'@'%'    TO 'detection'@'localhost';
GRANT 'role_ledger'@'%'       TO 'ledger'@'localhost';
GRANT 'role_readonly'@'%'     TO 'readonly'@'localhost';

SET DEFAULT ROLE 'role_admin'@'%'        TO 'admin'@'localhost';
SET DEFAULT ROLE 'role_app'@'%'          TO 'app'@'localhost';
SET DEFAULT ROLE 'role_manufacturer'@'%' TO 'p_5'@'localhost';
SET DEFAULT ROLE 'role_retailer'@'%'     TO 'p_23'@'localhost';
SET DEFAULT ROLE 'role_detection'@'%'    TO 'detection'@'localhost';
SET DEFAULT ROLE 'role_ledger'@'%'       TO 'ledger'@'localhost';
SET DEFAULT ROLE 'role_readonly'@'%'     TO 'readonly'@'localhost';
