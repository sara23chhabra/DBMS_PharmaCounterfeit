-- create local demo login accounts and assign the existing project roles
-- run this file using a MySQL administrator account
-- MySQL generates a separate random password for each account and prints it
-- save those passwords securely; do not commit them to the repository

CREATE USER 'admin'@'localhost' IDENTIFIED BY RANDOM PASSWORD;
GRANT 'role_admin'@'%' TO 'admin'@'localhost';
SET DEFAULT ROLE 'role_admin'@'%' TO 'admin'@'localhost';

CREATE USER 'app'@'localhost' IDENTIFIED BY RANDOM PASSWORD;
GRANT 'role_app'@'%' TO 'app'@'localhost';
SET DEFAULT ROLE 'role_app'@'%' TO 'app'@'localhost';

CREATE USER 'p_5'@'localhost' IDENTIFIED BY RANDOM PASSWORD;
GRANT 'role_manufacturer'@'%' TO 'p_5'@'localhost';
SET DEFAULT ROLE 'role_manufacturer'@'%' TO 'p_5'@'localhost';

CREATE USER 'p_23'@'localhost' IDENTIFIED BY RANDOM PASSWORD;
GRANT 'role_retailer'@'%' TO 'p_23'@'localhost';
SET DEFAULT ROLE 'role_retailer'@'%' TO 'p_23'@'localhost';

CREATE USER 'detection'@'localhost' IDENTIFIED BY RANDOM PASSWORD;
GRANT 'role_detection'@'%' TO 'detection'@'localhost';
SET DEFAULT ROLE 'role_detection'@'%' TO 'detection'@'localhost';

CREATE USER 'ledger'@'localhost' IDENTIFIED BY RANDOM PASSWORD;
GRANT 'role_ledger'@'%' TO 'ledger'@'localhost';
SET DEFAULT ROLE 'role_ledger'@'%' TO 'ledger'@'localhost';

CREATE USER 'readonly'@'localhost' IDENTIFIED BY RANDOM PASSWORD;
GRANT 'role_readonly'@'%' TO 'readonly'@'localhost';
SET DEFAULT ROLE 'role_readonly'@'%' TO 'readonly'@'localhost';

-- print the created local accounts and their assigned default roles
SELECT
    u.User AS login_name,
    u.Host AS login_host,
    r.From_user AS assigned_role,
    r.From_host AS role_host,
    r.With_admin_option AS admin_option
FROM mysql.user AS u
LEFT JOIN mysql.role_edges AS r
    ON r.To_user = u.User
   AND r.To_host = u.Host
WHERE u.Host = 'localhost'
  AND u.User IN (
      'admin',
      'app',
      'p_5',
      'p_23',
      'detection',
      'ledger',
      'readonly'
  )
ORDER BY u.User, r.From_user;
