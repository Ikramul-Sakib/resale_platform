```markdown
# ValuLens (`resale_platform`) — PostgreSQL Database Specification

## 1. Engine & Extensions
- **Database Engine:** PostgreSQL 15+ (mandatory for development, testing, and production; SQLite is never used).
- **Required PostgreSQL Extensions:** `btree_gist` (installed via `django.contrib.postgres.operations.BtreeGistExtension` in the initial `marketplaces` migration to support non-overlapping date-range `ExclusionConstraint` on `MarketplaceFeeRule`).

## 2. Foreign Key & Deletion Policy Matrix

| Child Entity | Foreign Key Field | Target Entity | `on_delete` Policy | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `Scan` | `user` (nullable) | `User` | `CASCADE` | User-owned private scans are deleted when the user deletes their account. |
| `ScanImage` | `scan` | `Scan` | `CASCADE` | Image metadata is removed when its parent scan is deleted (paired with storage file cleanup). |
| `IdentifiedItem` | `scan` | `Scan` | `CASCADE` | Recognition output belongs directly to the scan lifecycle. |
| `IdentifiedItem` | `category` | `Category` | `PROTECT` | Prevents deleting shared catalog categories referenced by identified items. |
| `IdentifiedItem` | `brand` (nullable) | `Brand` | `PROTECT` | Prevents deleting shared catalog brands referenced by identified items. |
| `PriceEstimate` | `identified_item` | `IdentifiedItem` | `CASCADE` | Estimates belong to the identified item. |
| `MarketPriceObservation` | `category` (nullable) | `Category` | `PROTECT` | Preserves category integrity for historical market observations. |
| `MarketPriceObservation` | `identified_item` (nullable) | `IdentifiedItem` | `SET_NULL` | Anonymized market observations remain valid even if a user deletes their scan. |
| `InventoryItem` | `user` | `User` | `CASCADE` | User-owned private inventory cascades on account deletion. |
| `InventoryItem` | `identified_item` (nullable) | `IdentifiedItem` | `SET_NULL` | Inventory item persists even if the original scan is purged. |
| `InventoryItem` | `category` | `Category` | `PROTECT` | Shared catalog reference protected against accidental deletion. |
| `InventoryItem` | `brand` (nullable) | `Brand` | `PROTECT` | Shared catalog reference protected against accidental deletion. |
| `ListingDraft` | `inventory_item` | `InventoryItem` | `CASCADE` | Drafts are removed if the underlying inventory item is deleted. |
| `ListingDraft` | `user` | `User` | `CASCADE` | User-owned private drafts cascade on account deletion. |
| `MarketplaceListingDraft` | `listing_draft` | `ListingDraft` | `CASCADE` | Marketplace-specific variations cascade with their parent draft. |
| `MarketplaceListingDraft` | `marketplace` | `Marketplace` | `PROTECT` | Cannot delete a marketplace that has active drafts. |
| `Sale` | `inventory_item` | `InventoryItem` | `PROTECT` | Prevents accidental deletion of an inventory item that has a recorded financial sale (unless cascading from full `User` deletion). |
| `Sale` | `user` | `User` | `CASCADE` | User-owned sales ledger cascades on full account deletion. |
| `Sale` | `marketplace` (nullable) | `Marketplace` | `PROTECT` | Preserves marketplace reference on historical sales. |
| `MarketplaceFeeRule` | `marketplace` | `Marketplace` | `PROTECT` | Prevents deleting a marketplace that has fee rules defined. |
| `MarketplaceFeeRule` | `category` (nullable) | `Category` | `PROTECT` | Prevents deleting a category referenced by fee schedules. |
| `ResaleIndexSnapshot` | `category` | `Category` | `PROTECT` | Protects categories that have historical index snapshots. |
| `AuditEvent` | `actor` (nullable) | `User` | `SET_NULL` | Security/audit trail survives account deletion with `actor_id = NULL`. |

## 3. Constraints & Indexes Inventory

### Check Constraints
1. **`scans_scan`:**
   - `ck_scan_completed_at_consistency`: `(status IN ('completed', 'failed') AND completed_at IS NOT NULL) OR (status IN ('pending', 'processing') AND completed_at IS NULL)`
   - `ck_scan_owner_or_session`: `user_id IS NOT NULL OR session_key <> ''`
2. **`scans_scanimage`:**
   - `ck_scanimage_file_size_positive`: `file_size > 0`
3. **`recognition_identifieditem`:**
   - `ck_identifieditem_confidence_range`: `confidence >= 0.0000 AND confidence <= 1.0000`
4. **`pricing_priceestimate`:**
   - `ck_priceestimate_ordered_non_negative`: `min_price >= 0.00 AND min_price <= typical_price AND typical_price <= max_price`
   - `ck_priceestimate_uncertainty_non_negative`: `uncertainty_score IS NULL OR uncertainty_score >= 0.0000`
5. **`pricing_marketpriceobservation`:**
   - `ck_observation_price_gt_zero`: `observed_price > 0.00`
6. **`inventory_inventoryitem`:**
   - `ck_inventory_purchase_price_non_negative`: `purchase_price IS NULL OR purchase_price >= 0.00`
   - `ck_inventory_est_value_non_negative`: `estimated_resale_value IS NULL OR estimated_resale_value >= 0.00`
7. **`listings_listingdraft`:**
   - `ck_listingdraft_price_non_negative`: `suggested_price >= 0.00`
8. **`listings_marketplacelistingdraft`:**
   - `ck_mplistdraft_price_non_negative`: `suggested_price >= 0.00`
9. **`inventory_sale`:**
   - `ck_sale_amounts_non_negative`: `sale_price >= 0.00 AND shipping_charged >= 0.00 AND shipping_cost >= 0.00 AND marketplace_fee >= 0.00 AND acquisition_cost >= 0.00`
10. **`marketplaces_marketplacefeerule`:**
    - `ck_feerule_percentage_range`: `percentage >= 0.0000 AND percentage <= 1.0000`
    - `ck_feerule_fixed_fee_non_negative`: `fixed_fee >= 0.00`
    - `ck_feerule_date_order`: `effective_to IS NULL OR effective_to >= effective_from`

### Unique & Exclusion Constraints
- `accounts_user`: `UNIQUE (email)`, `UNIQUE (public_id)`
- `catalog_category`: `UNIQUE (name)`, `UNIQUE (slug)`
- `catalog_brand`: `UNIQUE (name)`, `UNIQUE (slug)`
- `scans_scan`: `UNIQUE (public_id)`
- `scans_scanimage`: `UNIQUE (storage_key)`
- `recognition_identifieditem`: `UNIQUE (scan_id)`, `UNIQUE (public_id)`
- `listings_marketplacelistingdraft`: `UNIQUE (listing_draft_id, marketplace_id)`
- `inventory_sale`: `UNIQUE (inventory_item_id)`, `UNIQUE (public_id)`
- `analytics_resaleindexsnapshot`: `UNIQUE (category_id, period, currency, methodology)`
- `marketplaces_marketplacefeerule`: PostgreSQL GiST `ExclusionConstraint` `ex_feerule_no_overlapping_dates` on:
  - `(marketplace_id WITH =, COALESCE(category_id, 0) WITH =, daterange(effective_from, effective_to, '[]') WITH &&)`

### Performance Indexes
- `idx_scan_user_created`: `(user_id, created_at DESC)` on `scans_scan`
- `idx_scan_session_created`: `(session_key, created_at DESC)` on `scans_scan`
- `idx_observation_lookup`: `(product_key, observation_type, observed_on)` on `pricing_marketpriceobservation`
- `idx_inventory_user_status`: `(user_id, status)` on `inventory_inventoryitem`
- `idx_audit_actor_created`: `(actor_id, created_at DESC)` on `accounts_auditevent`

## 4. Backup and Restore Procedures (PostgreSQL)

### Creating a Compressed Custom-Format Backup
```bash
pg_dump --format=custom --no-owner --no-privileges \
  --dbname="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}" \
  --file="valulens_backup_$(date +%Y%m%d_%H%M%S).dump"