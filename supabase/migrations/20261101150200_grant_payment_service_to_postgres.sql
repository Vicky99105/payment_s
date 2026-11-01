-- Lets the admin role SET ROLE payment_service, so tests can verify the role's permissions without its password.
grant payment_service to postgres;
