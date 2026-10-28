from odoo import api, fields, models, _
from odoo.osv import expression
from odoo.exceptions import UserError
from odoo.tools import format_list, safe_eval, float_is_zero


class StockPicking(models.Model):
    _inherit = "stock.picking"

    pending_extra_product_count = fields.Integer(
        compute="_compute_extra_product_counters",
        string="Pending Extra Products",
    )
    rejected_extra_product_count = fields.Integer(
        compute="_compute_extra_product_counters",
        string="Rejected Extra Products",
    )
    extra_validation_blocked = fields.Boolean(
        compute="_compute_extra_product_counters",
        string="Extra Product Approval Blocking",
    )
    extra_purchase_order_ids = fields.Many2many(
        "purchase.order",
        compute="_compute_extra_purchase_orders",
        string="Related Purchase Orders",
    )
    extra_has_purchase_reference = fields.Boolean(
        compute="_compute_extra_purchase_orders",
        string="Has Purchase Reference",
    )
    shortfall_move_ids = fields.One2many(
        "stock.picking.shortfall",
        "picking_id",
        string="Shortfall Moves",
        copy=False,
    )
    batch_list_visible = fields.Boolean(
        compute="_compute_batch_list_visible",
        string="Show in Transfer Lists",
        store=True,
        index=True,
    )
    bti_detail_operation_line_ids = fields.One2many(
        "stock.move.line",
        "picking_id",
        compute="_compute_bti_detail_operation_line_ids",
        string="Detail Operations (Summary)",
    )

    @staticmethod
    def _bti_collect_deleted_move_line_ids(commands):
        delete_ids = set()
        for cmd in commands or []:
            if not isinstance(cmd, (list, tuple)) or len(cmd) < 2:
                continue
            if cmd[0] in (2, 3) and cmd[1]:
                delete_ids.add(cmd[1])
        return delete_ids

    @staticmethod
    def _bti_sanitize_move_line_commands(commands, delete_ids):
        if not commands or not delete_ids:
            return commands
        cleaned = []
        for cmd in commands:
            if not isinstance(cmd, (list, tuple)) or len(cmd) < 2:
                cleaned.append(cmd)
                continue
            if cmd[0] in (1, 4) and cmd[1] in delete_ids:
                continue
            if cmd[0] == 6:
                ids = [rec_id for rec_id in (cmd[2] or []) if rec_id not in delete_ids]
                cleaned.append((cmd[0], cmd[1], ids))
                continue
            cleaned.append(cmd)
        return cleaned

    def write(self, vals):
        if "move_line_ids" in vals or "move_ids_without_package" in vals:
            delete_ids = set()
            delete_ids |= self._bti_collect_deleted_move_line_ids(vals.get("move_line_ids"))
            for cmd in vals.get("move_ids_without_package") or []:
                if not isinstance(cmd, (list, tuple)) or len(cmd) < 3:
                    continue
                if cmd[0] in (0, 1) and isinstance(cmd[2], dict) and "move_line_ids" in cmd[2]:
                    delete_ids |= self._bti_collect_deleted_move_line_ids(cmd[2].get("move_line_ids"))
            if delete_ids:
                vals = dict(vals)
                if "move_line_ids" in vals:
                    vals["move_line_ids"] = self._bti_sanitize_move_line_commands(
                        vals["move_line_ids"], delete_ids
                    )
                if "move_ids_without_package" in vals:
                    sanitized_moves = []
                    for cmd in vals["move_ids_without_package"]:
                        if (
                            isinstance(cmd, (list, tuple))
                            and len(cmd) >= 3
                            and cmd[0] in (0, 1)
                            and isinstance(cmd[2], dict)
                            and "move_line_ids" in cmd[2]
                        ):
                            move_vals = dict(cmd[2])
                            move_vals["move_line_ids"] = self._bti_sanitize_move_line_commands(
                                move_vals.get("move_line_ids"), delete_ids
                            )
                            sanitized_moves.append((cmd[0], cmd[1], move_vals))
                        else:
                            sanitized_moves.append(cmd)
                    vals["move_ids_without_package"] = sanitized_moves
        return super().write(vals)


    @api.depends("move_ids.extra_product_state", "move_ids.purchase_line_id")
    def _compute_extra_product_counters(self):
        for picking in self:
            relevant_moves = picking.move_ids.filtered(
                lambda move: move.picking_id == picking and move._requires_extra_product_approval()
            )
            pending = relevant_moves.filtered(
                lambda move: move.extra_product_state == "pending"
            )
            rejected = relevant_moves.filtered(
                lambda move: move.extra_product_state == "rejected"
            )
            picking.pending_extra_product_count = len(pending)
            picking.rejected_extra_product_count = len(rejected)
            picking.extra_validation_blocked = bool(pending or rejected)

    @api.depends(
        "purchase_id",
        "move_ids.purchase_line_id.order_id",
        "move_ids.move_orig_ids.purchase_line_id.order_id",
        "batch_id.purchase_order_ids",
    )
    def _compute_extra_purchase_orders(self):
        PurchaseOrder = self.env["purchase.order"]
        for picking in self:
            orders = picking.purchase_id or PurchaseOrder.browse()
            orders |= picking.move_ids.purchase_line_id.mapped("order_id")
            orders |= picking.move_ids.move_orig_ids.purchase_line_id.mapped("order_id")
            related_lines = picking.move_ids._get_related_purchase_lines()
            if related_lines:
                orders |= related_lines.mapped("order_id")
            if picking.batch_id:
                orders |= picking.batch_id.purchase_order_ids
            picking.extra_purchase_order_ids = orders
            picking.extra_has_purchase_reference = bool(orders)

    @api.depends("batch_id", "batch_id.picking_ids", "batch_id.picking_type_id")
    def _compute_batch_list_visible(self):
        rep_by_batch = {}
        for batch in self.mapped("batch_id"):
            pickings = batch.picking_ids
            if not pickings:
                continue
            preferred = pickings
            if batch.picking_type_id:
                preferred = pickings.filtered(lambda p: p.picking_type_id == batch.picking_type_id)
            if not preferred:
                preferred = pickings
            rep_by_batch[batch.id] = preferred.sorted(key=lambda p: p.id)[0].id

        for picking in self:
            if not picking.batch_id:
                picking.batch_list_visible = True
            else:
                picking.batch_list_visible = picking.id == rep_by_batch.get(picking.batch_id.id)

    @api.depends(
        "move_line_ids",
        "move_line_ids.product_id",
        "move_line_ids.lot_id",
        "move_line_ids.lot_name",
        "move_line_ids.location_dest_id",
        "move_line_ids.quantity",
        "move_line_ids.bti_is_lot_summary_leader",
        "move_line_ids.bti_lot_summary_qty",
    )
    def _compute_bti_detail_operation_line_ids(self):
        for picking in self:
            lines = picking.move_line_ids.filtered(
                lambda line: line.bti_is_lot_summary_leader and not float_is_zero(
                    line.bti_lot_summary_qty,
                    precision_rounding=line.product_uom_id.rounding or 0.0001,
                )
            )
            picking.bti_detail_operation_line_ids = lines.sorted(
                key=lambda line: (
                    line.product_id.display_name or "",
                    line.lot_display_name or "",
                    line.location_dest_id.complete_name or line.location_dest_id.display_name or "",
                    line.id,
                )
            )

    def button_validate(self):
        self._ensure_no_pending_extra_products()
        shortfall_map = {picking.id: picking.shortfall_move_ids for picking in self}
        res = super().button_validate()
        self._process_shortfall_backorders(shortfall_map)
        return res

    def action_open_batch_or_self(self):
        self.ensure_one()
        if self.batch_id:
            return self.action_view_batch()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": self.id,
            "view_mode": "form",
        }

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        if self.batch_id:
            return self.action_view_batch()
        return super().get_formview_action(access_uid=access_uid)

    def action_next_transfer(self):
        next_transfers = self._get_next_transfers()
        if len(next_transfers) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "views": [[False, "form"]],
                "res_id": next_transfers.id,
            }

        domain = [("id", "in", next_transfers.ids)]
        if next_transfers:
            domain = expression.AND([domain, [("batch_list_visible", "=", True)]])

        return {
            "name": _("Next Transfers"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "views": [[False, "list"], [False, "form"]],
            "domain": domain,
        }

    def _ensure_no_pending_extra_products(self):
        for picking in self:
            if picking.picking_type_id.code not in {"incoming", "internal"}:
                continue
            if not picking.extra_has_purchase_reference:
                continue
            moves = picking.move_ids
            newly_flagged = moves.filtered(
                lambda m: m.extra_product_state == "not_required" and m._requires_extra_product_approval()
            )
            if newly_flagged:
                newly_flagged._initialize_extra_product_state()
            blocking_moves = moves.filtered(
                lambda m: m._requires_extra_product_approval() and m.extra_product_state in {"pending", "rejected"}
            )
            if not blocking_moves:
                continue
            product_names = format_list(
                self.env,
                blocking_moves.mapped(lambda m: "%s (%s %s)" % (
                    m.product_id.display_name,
                    m.product_uom_qty,
                    m.product_uom.name,
                )),
            )
            raise UserError(
                _(
                    "You must approve or remove the pending extra products before validating this receipt:\n%s"
                )
                % product_names
            )

    def action_open_add_extra_move_wizard(self):
        self.ensure_one()
        if self.picking_type_id.code not in {"incoming", "internal"} or not self.extra_has_purchase_reference:
            raise UserError(_("Extra products can only be added to receipts or quality control transfers linked to a purchase order."))
        ctx = dict(self.env.context or {})
        ctx.update({"default_picking_id": self.id})
        if self.batch_id:
            ctx.setdefault("default_batch_id", self.batch_id.id)
        if self.extra_purchase_order_ids:
            ctx["extra_related_purchase_order_ids"] = self.extra_purchase_order_ids.ids
        return {
            "type": "ir.actions.act_window",
            "name": _("Add Extra Product"),
            "res_model": "add.extra.move.wizard",
            "view_mode": "form",
            "target": "new",
            "context": ctx,
        }

    def _process_shortfall_backorders(self, shortfall_map):
        Move = self.env["stock.move"]
        for picking in self:
            shortfalls = shortfall_map.get(picking.id)
            if not shortfalls:
                continue
            shortfalls = shortfalls.with_context(prefetch_fields=False)
            shortfalls = shortfalls.exists()
            if not shortfalls:
                continue
            backorder = self.env["stock.picking"].search(
                [("backorder_id", "=", picking.id)], order="id desc", limit=1
            )
            if not backorder:
                backorder = picking._create_backorder_picking()
            new_moves = Move.browse()
            for shortfall in shortfalls:
                qty = shortfall.quantity
                if not qty:
                    continue
                move_vals = {
                    "name": shortfall.product_id.display_name,
                    "product_id": shortfall.product_id.id,
                    "product_uom": shortfall.product_uom_id.id,
                    "product_uom_qty": qty,
                    "picking_id": backorder.id,
                    "location_id": backorder.location_id.id,
                    "location_dest_id": backorder.location_dest_id.id,
                    "company_id": backorder.company_id.id,
                    "partner_id": backorder.partner_id.id if backorder.partner_id else False,
                }
                if shortfall.purchase_line_id:
                    move_vals["purchase_line_id"] = shortfall.purchase_line_id.id
                new_moves |= Move.create(move_vals)
            if new_moves:
                new_moves._action_confirm()
                if backorder.batch_id:
                    backorder.batch_id.with_context(batch_force_product_sync=True)._sync_product_summaries()
            shortfalls.unlink()

class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    def action_batch(self):
        action = super().action_batch()
        if not self:
            return action

        domain = action.get("domain") or "[]"
        if isinstance(domain, str):
            domain = safe_eval.safe_eval(domain)
        context_value = action.get("context") or {}
        if isinstance(context_value, str):
            context = safe_eval.safe_eval(context_value)
        else:
            context = dict(context_value)

        picking_types = self.filtered(lambda pt: pt)
        if picking_types:
            if len(picking_types) == 1:
                picking_type = picking_types[0]
                domain = expression.AND([domain, [("picking_type_id", "=", picking_type.id)]])
                context.setdefault("search_default_picking_type_id", [picking_type.id])
                context.setdefault("default_picking_type_id", picking_type.id)
            else:
                domain = expression.AND([domain, [("picking_type_id", "in", picking_types.ids)]])
                context.setdefault("search_default_picking_type_id", picking_types.ids)

        action["domain"] = domain
        action["context"] = context
        return action
