-- Seed data for FIMS startup

-- Price types (8 levels)
INSERT INTO price_types (name, code, requires_auth, sort_order) VALUES
  ('Retail',            'RETAIL',    false, 1),
  ('Sale',              'SALE',      false, 2),
  ('Wholesale',         'WHOLE',     true,  3),
  ('Employee',          'EMPLOYEE',  true,  4),
  ('Tent',              'TENT',      false, 5),
  ('Clearance',         'CLEAR',     false, 6),
  ('Manager Override',  'MANAGER',   true,  7),
  ('Cost',              'COST',      true,  8)
ON CONFLICT (code) DO NOTHING;

-- Packaging units
INSERT INTO packaging_units (name) VALUES
  ('EACH'), ('PACK'), ('CASE'), ('DISPLAY'), ('PALLET')
ON CONFLICT (name) DO NOTHING;

-- User roles
INSERT INTO user_roles (name) VALUES
  ('ADMIN'), ('MANAGER'), ('CASHIER'), ('VIEWER')
ON CONFLICT (name) DO NOTHING;

-- Default admin user (password: changeme — hash with bcrypt before prod)
INSERT INTO users (username, display_name, hashed_password, role_id, is_active)
SELECT 'admin', 'Administrator', '$2b$12$placeholder', id, true
FROM user_roles WHERE name = 'ADMIN'
ON CONFLICT (username) DO NOTHING;
