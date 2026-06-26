-- FIMS DB mesh — Phase 1: schema foundation for last-write-wins (LWW) sync.
--
-- Idempotent. Apply identically on EVERY node, passing that node's offset:
--   psql ... -v node_name=pi     -v node_offset=0  -f mesh_phase1.sql
--   psql ... -v node_name=laptop -v node_offset=1  -f mesh_phase1.sql
--   psql ... -v node_name=pc     -v node_offset=2  -f mesh_phase1.sql
--
-- What it does, per SYNCABLE table (see list below):
--   1. adds  updated_at timestamptz NOT NULL DEFAULT now()  if missing
--   2. installs a BEFORE UPDATE trigger that bumps updated_at = now()
--   3. installs an AFTER DELETE trigger that records a tombstone
--   4. for integer-PK tables: repartitions the id sequence to INCREMENT BY 10
--      with this node's offset, so new inserts on different nodes never collide
--      (pi ids end in 0, laptop in 1, pc in 2). Existing rows keep their ids.
--
-- It also creates two infra tables:
--   mesh_node      — this node's identity (name, offset)
--   mesh_tombstone — deletes to propagate (table_name, row_pk, deleted_at)
--
-- TABLES DELIBERATELY NOT SYNCED (handled only by full backup/clone in dbmesh.sh):
--   alembic_version (schema version), email_accounts (node creds),
--   sales/sale_items/receipts/inventory_events (transactional ledger — LWW unsafe),
--   audit_logs (append-only), import_jobs/import_rows (per-node workflow),
--   users/user_roles (auth — add later if you want shared logins).

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- infra tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mesh_node (
    id          int PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton
    node_name   text NOT NULL,
    node_offset int  NOT NULL CHECK (node_offset BETWEEN 0 AND 9),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO mesh_node (id, node_name, node_offset)
VALUES (1, :'node_name', :node_offset)
ON CONFLICT (id) DO UPDATE
    SET node_name = EXCLUDED.node_name,
        node_offset = EXCLUDED.node_offset,
        updated_at = now();

CREATE TABLE IF NOT EXISTS mesh_tombstone (
    id          bigserial PRIMARY KEY,
    table_name  text NOT NULL,
    row_pk      text NOT NULL,
    deleted_at  timestamptz NOT NULL DEFAULT now(),
    node_name   text NOT NULL,
    UNIQUE (table_name, row_pk)
);
CREATE INDEX IF NOT EXISTS idx_mesh_tombstone_deleted_at ON mesh_tombstone (deleted_at);

-- ---------------------------------------------------------------------------
-- shared trigger functions
-- ---------------------------------------------------------------------------
-- Bump updated_at to now() on normal app updates, BUT preserve an explicitly
-- supplied value. The sync engine sets updated_at to the source row's timestamp;
-- if we always overwrote with now() the two nodes could never converge.
CREATE OR REPLACE FUNCTION mesh_bump_updated_at() RETURNS trigger AS $$
BEGIN
    IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION mesh_record_tombstone() RETURNS trigger AS $$
DECLARE
    me text;
BEGIN
    SELECT node_name INTO me FROM mesh_node WHERE id = 1;
    INSERT INTO mesh_tombstone (table_name, row_pk, deleted_at, node_name)
    VALUES (TG_TABLE_NAME, OLD.id::text, now(), COALESCE(me, 'unknown'))
    ON CONFLICT (table_name, row_pk)
        DO UPDATE SET deleted_at = now(), node_name = COALESCE(me, 'unknown');
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- apply foundation to each syncable table
-- ---------------------------------------------------------------------------
DO $outer$
DECLARE
    syncable text[] := ARRAY[
        'products', 'product_prices', 'price_history', 'product_categories',
        'product_brands', 'product_videos', 'product_barcodes', 'product_aliases',
        'product_costing', 'packaging_units', 'case_packs', 'price_types',
        'suppliers', 'supplier_products', 'manufacturers', 'importers',
        'brand_importers', 'brand_manufacturers', 'deals', 'deal_conditions',
        'deal_rewards', 'store_documents'
    ];
    t          text;
    id_type    text;
    seq_name   text;
    node_off   int;
    cur_last   bigint;
    new_start  bigint;
BEGIN
    SELECT node_offset INTO node_off FROM mesh_node WHERE id = 1;

    FOREACH t IN ARRAY syncable LOOP
        -- skip tables not present on this node
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = t
        ) THEN
            RAISE NOTICE 'skip % (absent)', t;
            CONTINUE;
        END IF;

        -- 1. updated_at column
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = t AND column_name = 'updated_at'
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()', t);
            RAISE NOTICE 'added updated_at to %', t;
        END IF;

        -- 2. bump-updated_at trigger
        EXECUTE format('DROP TRIGGER IF EXISTS trg_mesh_bump ON public.%I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_mesh_bump BEFORE UPDATE ON public.%I
             FOR EACH ROW EXECUTE FUNCTION mesh_bump_updated_at()', t);

        -- 3. tombstone trigger
        EXECUTE format('DROP TRIGGER IF EXISTS trg_mesh_tombstone ON public.%I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_mesh_tombstone AFTER DELETE ON public.%I
             FOR EACH ROW EXECUTE FUNCTION mesh_record_tombstone()', t);

        -- 4. interleaved id sequence (integer-PK tables only)
        SELECT data_type INTO id_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = t AND column_name = 'id';

        seq_name := pg_get_serial_sequence('public.' || quote_ident(t), 'id');

        IF id_type IN ('integer', 'bigint', 'smallint') AND seq_name IS NOT NULL THEN
            EXECUTE format('ALTER SEQUENCE %s INCREMENT BY 10', seq_name);
            -- next id must be > current max AND end in node_off (mod 10)
            EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM public.%I', t) INTO cur_last;
            new_start := ((cur_last / 10) + 1) * 10 + node_off;
            PERFORM setval(seq_name, new_start, false);  -- false: next nextval() = new_start
            RAISE NOTICE 'seq % -> increment 10, next %', seq_name, new_start;
        END IF;
    END LOOP;
END;
$outer$;

SELECT node_name, node_offset FROM mesh_node WHERE id = 1;
