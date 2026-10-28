# Batch Transfer Inward Entry

Enforces purchase-manager approval when extra products show up on receipts or internal transfers, including batch transfers. Extra moves are blocked from validation until approved or removed, and approved extras can be pushed into a purchase order line.

## Supported Scenarios

- Incoming receipts and internal transfers that are linked (directly or indirectly) to a purchase order.
- Batches (`stock.picking.batch`) and standalone receipts (`stock.picking`).

## Key Features

- Auto-detects extra products (moves without a related PO line) and marks them pending.
- Purchase manager approve/reject actions from batch moves, receipts, or purchase orders.
- Validate buttons are hidden or blocked while pending or rejected extras exist.
- Add Extra Product wizard for batches and receipts with optional price, discount, taxes, and lot/serial capture.
- On approval, creates a purchase order line using standard `_prepare_add_missing_fields`, applies extra price/discount/taxes when provided, and links the move.
- On rejection, cancels and deletes the move; chatter messages are posted on batch and receipt.
- Batch product summary with arrived quantity editing and a Detail Operations wizard for lot/serial allocation.
- Purchase order form and list show pending extra lines and warnings.
- Tracks shortfalls for removed moves and recreates them as backorder moves during validation.
- Batch completion can roll completed receipts into the next operation and prefill lots for internal transfers.

## Data Model Extensions

### `stock.move`

| Field | Type | Description |
| --- | --- | --- |
| `extra_product_state` | Selection | `not_required`, `pending`, `approved`, `rejected` |
| `target_purchase_order_id` | Many2one(`purchase.order`) | Target PO for the extra line |
| `available_target_purchase_order_ids` | Many2many(`purchase.order`) | Computed list of valid target POs |
| `extra_product_requested_by_id` / `extra_product_requested_on` | Audit | Who requested approval and when |
| `extra_product_reviewed_by_id` / `extra_product_reviewed_on` | Audit | Reviewer and timestamp |
| `extra_product_requires_approval` | Boolean (stored) | Helper for UI blocking |
| `extra_currency_id` | Many2one(`res.currency`) | Currency for extra pricing |
| `extra_price_unit` | Monetary | Optional unit price override |
| `extra_discount` | Float | Optional discount percentage |
| `extra_tax_ids` | Many2many(`account.tax`) | Optional vendor taxes |

### `stock.picking`

| Field | Type | Description |
| --- | --- | --- |
| `pending_extra_product_count` | Integer | Count of pending extras |
| `rejected_extra_product_count` | Integer | Count of rejected extras |
| `extra_validation_blocked` | Boolean | Blocks validation when pending or rejected exist |
| `extra_purchase_order_ids` | Many2many(`purchase.order`) | Related POs for the receipt |
| `extra_has_purchase_reference` | Boolean | True when receipt is linked to a PO |
| `shortfall_move_ids` | One2many(`stock.picking.shortfall`) | Shortfall records for backorders |

### `stock.picking.batch`

| Field | Type | Description |
| --- | --- | --- |
| `pending_extra_product_count` | Integer | Count of pending extras |
| `rejected_extra_product_count` | Integer | Count of rejected extras |
| `extra_validation_blocked` | Boolean | Blocks batch validation |
| `purchase_order_ids` | Many2many(`purchase.order`) | Related POs for the batch |
| `product_summary_ids` | One2many(`stock.picking.batch.product.summary`) | Batch product summary |

### `stock.picking.batch.product.summary`

| Field | Type | Description |
| --- | --- | --- |
| `demand_qty` | Float | Total demanded quantity in PO UoM |
| `arrived_qty` | Float | Editable arrived quantity for the batch |
| `extra_product_state` | Selection | Aggregated extra product state |
| `extra_product_requested_on` / `extra_product_requested_by_id` | Audit | Earliest pending request info |
| `target_purchase_order_display` | Char | Comma-separated target POs |
| `extra_has_pending` | Boolean | True when pending extras exist |

### `purchase.order`

| Field | Type | Description |
| --- | --- | --- |
| `batch_extra_move_ids` | Many2many(`stock.move`) | Extra moves targeting this PO |
| `batch_extra_move_ids_pending` | Many2many(`stock.move`) | Pending extra moves |
| `batch_pending_extra_move_count` | Integer | Pending count |

### `stock.picking.shortfall`

| Field | Type | Description |
| --- | --- | --- |
| `picking_id` | Many2one(`stock.picking`) | Source picking |
| `product_id` / `product_uom_id` / `quantity` | Required | Shortfall details |
| `purchase_line_id` | Many2one(`purchase.order.line`) | Optional PO line |

## Approval Workflow

1. Detection: an incoming or internal move without a related PO line is marked pending and logged in chatter.
2. Pending: batch or receipt warns and validation is blocked.
3. Approve: manager picks or validates target PO; a PO line is created and linked, state becomes approved.
4. Reject: manager rejects; move is canceled and removed (qty done must be zero).
5. Validate: once no pending or rejected extras remain, validation proceeds.

## User Interface

- Batch: Add Extra Product button, Products tab summary, approval buttons, and Detail Operations wizard.
- Receipt: Add Extra Product button, warning banner, inline approve/reject, and target PO column.
- Purchase Order: pending extras list in the Products tab and warning badge in list view.
- Detail Operations tab on pickings to edit lot/serial info with cleaned lot display.

## Security

- Approve and reject actions require `purchase.group_purchase_manager`.
- Wizards are available to base users; batch summary and shortfalls are visible to stock users.

## Configuration and Installation

1. Place the module in your addons path.
2. Update Apps list.
3. Install Batch Transfer Inward Entry.
4. Ensure Purchase Managers are in the Purchase / Administrator group.

## Usage Notes

- Extra products are only flagged when the receipt has a purchase reference; unrelated internal moves are ignored.
- Use the Add Extra Product wizard to set price, discount, taxes, and lot or serial details before approval.
- Serial-tracked products must use quantity 1 in the wizard.
- Rejections require qty done to be zero; clear move lines first.
- Target PO must be related to the batch or receipt, otherwise approval is blocked.

## Technical Notes

- Uses Odoo 17+ modifiers in views.
- Batch product summaries sync on read and write and can push arrived quantities back to move lines.

## Troubleshooting

- Validation blocked after approval: verify all extra moves show Approved and are linked to a PO line.
- Cannot approve: user must be in Purchase Manager group and target PO must match the vendor.
- Lot or serial errors: ensure serial products have quantity 1 and a lot or serial value.

## Publisher

**Next Page Technologies Pvt Ltd**  
https://nextpagetechnologies.com
