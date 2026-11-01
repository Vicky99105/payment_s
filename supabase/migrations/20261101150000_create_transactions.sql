-- Transactions received from payment-processor webhooks, plus an append-only delivery log.

create table public.transactions (
  transaction_id      text primary key,
  source_account      text not null,
  destination_account text not null,
  amount              numeric(18,2) not null check (amount > 0),
  currency            char(3) not null check (currency ~ '^[A-Z]{3}$'),
  status              text not null default 'PROCESSING'
                        check (status in ('PROCESSING', 'PROCESSED')),
  attempts            integer not null default 0,
  last_error          text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  processed_at        timestamptz,
  constraint transactions_processed_at_matches_status
    check ((status = 'PROCESSED') = (processed_at is not null))
);

create table public.webhook_deliveries (
  id             bigint generated always as identity primary key,
  transaction_id text not null,
  payload        jsonb not null,
  received_at    timestamptz not null default now()
);

create index webhook_deliveries_transaction_id_idx
  on public.webhook_deliveries (transaction_id);

-- No policies: Supabase's public REST API (anon / authenticated keys) cannot read or write these tables.
-- The service connects with a dedicated database role instead.
alter table public.transactions enable row level security;
alter table public.webhook_deliveries enable row level security;
