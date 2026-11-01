-- Least-privilege role the service connects as. The password is set out of band, never in a migration.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'payment_service') then
    create role payment_service login noinherit;
  end if;
end
$$;

grant usage on schema public to payment_service;
grant select, insert, update on public.transactions to payment_service;
grant select, insert on public.webhook_deliveries to payment_service;

-- RLS stays on. Only this role gets policies, so anon / authenticated still see nothing.
create policy payment_service_all_transactions on public.transactions
  for all to payment_service using (true) with check (true);
create policy payment_service_all_webhook_deliveries on public.webhook_deliveries
  for all to payment_service using (true) with check (true);
