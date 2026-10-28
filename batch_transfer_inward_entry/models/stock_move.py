from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class StockMove(models.Model):
    _inherit = "stock.move"

    extra_product_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("pending", "Pending Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Extra Product Approval",
        default="not_required",
        copy=False,
    )
    target_purchase_order_id = fields.Many2one(
        "purchase.order",
        string="Target Purchase Order",
        copy=False,
        help="Purchase order that must receive the extra product line once it is approved.",
    )
    available_target_purchase_order_ids = fields.Many2many(
        "purchase.order",
        compute="_compute_available_target_purchase_orders",
        string="Selectable Purchase Orders",
    )
    extra_product_requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        readonly=True,
        copy=False,
    )
    extra_product_requested_on = fields.Datetime(
        string="Requested On",
        readonly=True,
        copy=False,
    )
    extra_product_reviewed_by_id = fields.Many2one(
        "res.users",
        string="Reviewed By",
        readonly=True,
        copy=False,
    )
    extra_product_reviewed_on = fields.Datetime(
        string="Reviewed On",
        readonly=True,
        copy=False,
    )
    extra_product_requires_approval = fields.Boolean(compute="_compute_extra_product_requires_approval", store=True)
    extra_currency_id = fields.Many2one(
        "res.currency",
        string="Extra Currency",
        copy=False,
        default=lambda self: self.env.company.currency_id,
    )
    extra_price_unit = fields.Monetary(
        string="Extra Unit Price",
        currency_field="extra_currency_id",
        copy=False,
        default=0.0,
    )
    extra_discount = fields.Float(
        string="Extra Discount (%)",
        copy=False,
        default=0.0,
    )
    extra_tax_ids = fields.Many2many(
        "account.tax",
        "stock_move_extra_tax_rel",
        "move_id",
        "tax_id",
        string="Extra Vendor Taxes",
        copy=False,
        domain=[("type_tax_use", "=", "purchase")],
    )

    _EXTRA_SKIP_CONTEXT_KEY = "skip_batch_extra_product_sync"

    @api.depends("extra_product_state")
    def _compute_extra_product_requires_approval(self):
        for move in self:
            move.extra_product_requires_approval = move.extra_product_state in {"pending", "rejected"}

    @api.depends(
        "picking_id",
        "picking_id.batch_id.purchase_order_ids",
        "picking_id.purchase_id",
        "partner_id",
    )
    def _compute_available_target_purchase_orders(self):
        PurchaseOrder = self.env["purchase.order"]
        for move in self:
            candidates = PurchaseOrder.browse()
            picking = move.picking_id
            if picking and picking.batch_id:
                candidates = picking.batch_id.purchase_order_ids
            elif picking and picking.purchase_id:
                candidates = picking.purchase_id
            elif move.partner_id:
                candidates = PurchaseOrder.search(
                    [
                        ("partner_id", "=", move.partner_id.id),
                        ("state", "in", ("draft", "sent", "to approve", "purchase", "done")),
                    ]
                )
            if picking and getattr(picking, "extra_purchase_order_ids", False):
                candidates |= picking.extra_purchase_order_ids
            related_lines = move._get_related_purchase_lines()
            if related_lines:
                candidates |= related_lines.mapped("order_id")
            move.available_target_purchase_order_ids = candidates

    @api.onchange("available_target_purchase_order_ids")
    def _onchange_available_target_purchase_orders(self):
        for move in self:
            values = move.available_target_purchase_order_ids.ids
            domain = [("id", "in", values)] if values else []
            if move.target_purchase_order_id and move.target_purchase_order_id.id not in values:
                move.target_purchase_order_id = False
            return {"domain": {"target_purchase_order_id": domain}}

    @api.model_create_multi
    def create(self, vals_list):
        Batch = self.env['stock.picking.batch']
        for vals in vals_list:
            # triggered from Batch UI
            if self._context.get('batch_context_from_form'):
                batch = Batch.browse(self._context.get('active_id') or self._context.get('batch_id'))
                if batch:
                    # fallback: pick the first incoming picking
                    picking = batch.picking_ids.filtered(lambda p: p.picking_type_id.code == 'incoming')[:1]
                    if picking:
                        vals.setdefault('picking_id', picking.id)
                        vals.setdefault('location_id', picking.location_id.id)
                        vals.setdefault('location_dest_id', picking.location_dest_id.id)
                        vals.setdefault('company_id', picking.company_id.id)
                        vals.setdefault('partner_id', picking.partner_id.id)
        moves = super().create(vals_list)
        moves._initialize_extra_product_state()
        batches = moves.mapped("picking_id.batch_id")
        if batches:
            batches.with_context(batch_force_product_sync=True)._sync_product_summaries()
        return moves


    def write(self, vals):
        if "move_line_ids" in vals and len(self) == 1:
            # When the serial/lot generator replaces move lines, keep the first
            # line id by converting the first delete+create pair into an update.
            vals = dict(vals)
            vals["move_line_ids"] = self._reuse_generated_move_line_commands(
                vals["move_line_ids"]
            )
        batches = self.env["stock.picking.batch"].browse()
        res = super().write(vals)
        if not self.env.context.get(self._EXTRA_SKIP_CONTEXT_KEY):
            self._synchronize_extra_product_state()
        if (
            not self.env.context.get("batch_skip_summary_sync")
            and any(
                field in vals
                for field in (
                    "product_uom_qty",
                    "quantity",
                    "state",
                    "purchase_line_id",
                    "picking_id",
                )
            )
        ):
            batches = self.mapped("picking_id.batch_id")
        if batches:
                batches._sync_product_summaries()
        return res

    @staticmethod
    def _reuse_generated_move_line_commands(commands):
        """Replace the first delete+create pair with an update to keep the line id stable.

        The Generate Serials/Lots dialog sends commands that delete existing move lines
        and recreate them. The web client may still hold a reference to the first line id,
        so we preserve that id by reusing the first delete target for the first create vals.
        """
        try:
            delete_pos = next(
                i for i, cmd in enumerate(commands) if cmd and cmd[0] in (2, 3) and cmd[1]
            )
            create_pos = next(
                i
                for i, cmd in enumerate(commands)
                if cmd and cmd[0] == 0 and isinstance(cmd[2], dict)
            )
        except StopIteration:
            return commands

        delete_cmd = commands[delete_pos]
        create_cmd = commands[create_pos]
        create_vals = create_cmd[2] or {}

        # Only tweak when it looks like a lot/serial generation payload.
        if not any(key in create_vals for key in ("lot_id", "lot_name")):
            return commands

        new_commands = list(commands)
        new_commands[delete_pos] = (1, delete_cmd[1], create_vals)
        # Remove the create command we just reused (account for shift if needed).
        if create_pos > delete_pos:
            new_commands.pop(create_pos)
        else:
            new_commands.pop(create_pos)
        return new_commands

    def unlink(self):
        PickingShortfall = self.env["stock.picking.shortfall"]
        shortfall_vals = []
        for move in self:
            if move.state == "cancel":
                continue
            picking = move.picking_id
            if (
                picking
                and picking.picking_type_id.code in {"incoming", "internal"}
                and picking.state in {"draft", "confirmed", "assigned", "waiting"}
                and not self.env.context.get("skip_shortfall_record")
            ):
                if "quantity_done" in move._fields:
                    quantity_done = move.quantity_done
                else:
                    quantity_done = sum(
                        getattr(line, "qty_done", line.quantity)
                        for line in move.move_line_ids
                    )
                qty_shortfall = move.product_uom_qty - quantity_done
                if float_is_zero(
                    qty_shortfall,
                    precision_rounding=move.product_uom.rounding or move.product_uom.factor or 0.0001,
                ):
                    continue
                shortfall_vals.append(
                    {
                        "picking_id": picking.id,
                        "product_id": move.product_id.id,
                        "product_uom_id": move.product_uom.id,
                        "quantity": qty_shortfall,
                        "purchase_line_id": move.purchase_line_id.id if move.purchase_line_id else False,
                    }
                )
        batches = self.mapped("picking_id.batch_id")
        res = super().unlink()
        if shortfall_vals:
            PickingShortfall.create(shortfall_vals)
        if batches:
            batches.with_context(batch_force_product_sync=True)._sync_product_summaries()
        return res

    def action_approve_extra_product(self):
        self._check_is_purchase_manager()
        approval_time = fields.Datetime.now()
        order_line_model = self.env["purchase.order.line"]
        for move in self:
            if move.extra_product_state == "approved":
                continue
            move._ensure_pending_extra_product()
            target_po = move._get_target_purchase_order()
            po_line = move._ensure_purchase_order_line(target_po, order_line_model)
            move.with_context({self._EXTRA_SKIP_CONTEXT_KEY: True}).write(
                {
                    "purchase_line_id": po_line.id,
                    "extra_product_state": "approved",
                    "extra_product_reviewed_by_id": self.env.user.id,
                    "extra_product_reviewed_on": approval_time,
                }
            )
            move._notify_batch_on_decision("approved")

        draft_moves = self.filtered(lambda move: move.state == "draft")
        if draft_moves:
            draft_moves._action_confirm()

        assignable_moves = self.filtered(
            lambda move: move.state in {"confirmed", "waiting", "partially_available"}
        )
        if assignable_moves:
            assignable_moves._action_assign()
        return True

    def action_reject_extra_product(self):
        self._check_is_purchase_manager()
        moves_to_remove = self.env["stock.move"]
        for move in self:
            if move.state not in {"draft", "confirmed", "waiting", "assigned"}:
                raise UserError(
                    _("Only pending moves can be rejected before validation.")
                )
            rounding = move.product_uom.rounding or move.product_uom.factor or 0.0001
            if any(
                not float_is_zero(ml.quantity, precision_rounding=rounding)
                for ml in move.move_line_ids
            ):
                raise UserError(
                    _(
                        "Remove any entered done quantities for %s before rejecting the extra product."
                    )
                    % move.display_name
                )
            if move.extra_product_state not in {"pending", "rejected"}:
                continue
            move.with_context({self._EXTRA_SKIP_CONTEXT_KEY: True}).write(
                {
                    "extra_product_state": "rejected",
                    "extra_product_reviewed_by_id": self.env.user.id,
                    "extra_product_reviewed_on": fields.Datetime.now(),
                }
            )
            move._notify_batch_on_decision("rejected")
            moves_to_remove |= move
        if moves_to_remove:
            moves_to_remove._action_cancel()
            moves_to_remove.unlink()
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _initialize_extra_product_state(self):
        now = fields.Datetime.now()
        for move in self:
            if not move._requires_extra_product_approval():
                continue
            updates = {
                "extra_product_state": "pending",
                "extra_product_requested_by_id": self.env.user.id,
                "extra_product_requested_on": now,
                "extra_product_requires_approval": True,
            }
            default_po = move._get_default_target_purchase_order()
            if default_po and not move.target_purchase_order_id:
                updates["target_purchase_order_id"] = default_po.id
            move.with_context({self._EXTRA_SKIP_CONTEXT_KEY: True}).write(updates)
            move._notify_batch_on_pending()

    def _synchronize_extra_product_state(self):
        for move in self:
            if move.purchase_line_id and move.extra_product_state == "pending":
                move.with_context({self._EXTRA_SKIP_CONTEXT_KEY: True}).write(
                    {
                        "extra_product_state": "approved",
                        "extra_product_reviewed_by_id": self.env.user.id,
                        "extra_product_reviewed_on": fields.Datetime.now(),
                    }
                )
            elif (
                not move._requires_extra_product_approval()
                and move.extra_product_state != "not_required"
                and not move.purchase_line_id
            ):
                move.with_context({self._EXTRA_SKIP_CONTEXT_KEY: True}).write(
                    {
                        "extra_product_state": "not_required",
                        "extra_product_requested_by_id": False,
                        "extra_product_requested_on": False,
                        "extra_product_reviewed_by_id": False,
                        "extra_product_reviewed_on": False,
                    }
                )

    def _requires_extra_product_approval(self):
        self.ensure_one()
        picking = self.picking_id
        if not picking:
            return False
        if picking.picking_type_id.code not in {"incoming", "internal"}:
            return False
        if picking.state in ("done", "cancel"):
            return False
        if not getattr(picking, "extra_has_purchase_reference", False):
            return False
        related_lines = self._get_related_purchase_lines()
        return not bool(related_lines)

    def _get_related_purchase_lines(self, visited=None):
        if visited is None:
            visited = set()
        PurchaseOrderLine = self.env["purchase.order.line"]
        lines = PurchaseOrderLine.browse()
        for move in self:
            if move.id in visited:
                continue
            visited.add(move.id)
            if move.purchase_line_id:
                lines |= move.purchase_line_id
            origin_moves = move.move_orig_ids
            if origin_moves:
                lines |= origin_moves._get_related_purchase_lines(visited)
            dest_moves = move.move_dest_ids.filtered(
                lambda m: m.picking_id and m.picking_id.picking_type_id.code in {"incoming", "internal"}
            )
            if dest_moves:
                lines |= dest_moves._get_related_purchase_lines(visited)
        return lines

    def _ensure_pending_extra_product(self):
        self.ensure_one()
        if not self._requires_extra_product_approval():
            raise UserError(
                _("This move is not marked as an extra product that needs approval.")
            )
        if self.extra_product_state not in {"pending", "rejected"}:
            raise UserError(
                _("Only pending or previously rejected extra product lines can be approved.")
            )

    def _get_default_target_purchase_order(self):
        self.ensure_one()
        purchase = self.picking_id.purchase_id if self.picking_id else False
        return purchase

    def _get_target_purchase_order(self):
        self.ensure_one()
        target = self.target_purchase_order_id or self._get_default_target_purchase_order()
        if not target:
            raise UserError(
                _("Define the purchase order that must receive the extra product for %s.")
                % self.product_id.display_name
            )
        available = self.available_target_purchase_order_ids
        if available and target not in available:
            raise UserError(
                _("Select one of the purchase orders attached to this batch/receipt.")
            )
        move_partner = self.partner_id.commercial_partner_id if self.partner_id else False
        if move_partner and target.partner_id.commercial_partner_id != move_partner:
            raise UserError(
                _("The selected purchase order must belong to vendor %s.")
                % move_partner.display_name
            )
        return target

    def _ensure_purchase_order_line(self, purchase_order, order_line_model):
        self.ensure_one()
        product = self.product_id
        if not product:
            raise UserError(
                _("Specify a product on the move before approving the extra line.")
            )
        if self.purchase_line_id:
            if self.purchase_line_id.order_id != purchase_order:
                raise UserError(
                    _(
                        "The move is already linked to purchase order %s."
                    )
                    % self.purchase_line_id.order_id.display_name
                )
            return self.purchase_line_id
        qty_done = sum(self.move_line_ids.mapped("quantity"))
        qty = qty_done or getattr(self, "quantity", 0.0) or self.product_uom_qty
        rounding = (self.product_uom or product.uom_id).rounding
        if not qty or float_is_zero(qty, precision_rounding=rounding):
            raise UserError(
                _("The received quantity for %s must be greater than zero.")
                % product.display_name
            )
        po_uom = product.uom_po_id
        po_qty = self.product_uom._compute_quantity(
            qty, po_uom, rounding_method="HALF-UP"
        )
        line_vals = {
            "order_id": purchase_order.id,
            "product_id": product.id,
            "product_qty": po_qty,
            "product_uom": po_uom.id,
        }
        line_vals.update(order_line_model._prepare_add_missing_fields(line_vals))
        currency = self.extra_currency_id or purchase_order.currency_id
        rounding = currency.rounding if currency else self.env.company.currency_id.rounding
        if not float_is_zero(self.extra_price_unit, precision_rounding=rounding):
            price_unit = self.extra_price_unit
            if (
                self.extra_currency_id
                and purchase_order.currency_id
                and self.extra_currency_id != purchase_order.currency_id
            ):
                price_unit = self.extra_currency_id._convert(
                    price_unit,
                    purchase_order.currency_id,
                    self.company_id or self.env.company,
                    purchase_order.date_order or fields.Date.context_today(self),
                )
            line_vals["price_unit"] = price_unit
        line_vals["discount"] = self.extra_discount or 0.0
        if self.extra_tax_ids:
            line_vals["taxes_id"] = [(6, 0, self.extra_tax_ids.ids)]
        po_line = order_line_model.with_context(skip_change_approval=True).create(line_vals)
        # Link this move to the new purchase order line and remove any auto-created moves
        extra_moves = (po_line.move_ids - self).filtered(lambda m: m.state not in ("done", "cancel"))
        if extra_moves:
            extra_moves.with_context(skip_shortfall_record=True)._action_cancel()
            extra_moves.with_context(skip_shortfall_record=True).unlink()
        return po_line

    def _notify_batch_on_pending(self):
        for move in self:
            batch = move.picking_id.batch_id
            if not batch:
                continue
            message = _(
                "Product %(product)s (%(qty)s %(uom)s) was added to batch %(batch)s for purchase %(po)s "
                "and requires purchase manager approval.",
                product=move.product_id.display_name,
                qty=move.product_uom_qty,
                uom=move.product_uom.name,
                batch=batch.display_name,
                po=move.picking_id.purchase_id.display_name
                if move.picking_id.purchase_id
                else move.picking_id.name,
            )
            batch.message_post(body=message, subtype_xmlid="mail.mt_comment")
        self._notify_picking_on_pending()

    def _notify_batch_on_decision(self, decision):
        for move in self:
            batch = move.picking_id.batch_id
            if not batch:
                continue
            po_name = move.target_purchase_order_id.display_name or (
                move.picking_id.purchase_id.display_name if move.picking_id.purchase_id else ""
            )
            if decision == "approved":
                message = _(
                    "Extra product %(product)s (%(qty)s %(uom)s) was approved and linked to purchase order %(po)s.",
                    product=move.product_id.display_name,
                    qty=move.product_uom_qty,
                    uom=move.product_uom.name,
                    po=po_name,
                )
            else:
                message = _(
                    "Extra product %(product)s (%(qty)s %(uom)s) was rejected and removed from the batch.",
                    product=move.product_id.display_name,
                    qty=move.product_uom_qty,
                    uom=move.product_uom.name,
                )
            batch.message_post(body=message, subtype_xmlid="mail.mt_note")
        self._notify_picking_on_decision(decision)

    def _notify_picking_on_pending(self):
        for move in self:
            picking = move.picking_id
            if not picking or not picking.purchase_id:
                continue
            message = _(
                "Product %(product)s (%(qty)s %(uom)s) was added to receipt %(picking)s for purchase %(po)s and requires purchase manager approval.",
                product=move.product_id.display_name,
                qty=move.product_uom_qty,
                uom=move.product_uom.name,
                picking=picking.display_name,
                po=picking.purchase_id.display_name,
            )
            picking.message_post(body=message, subtype_xmlid="mail.mt_comment")

    def _notify_picking_on_decision(self, decision):
        for move in self:
            picking = move.picking_id
            if not picking:
                continue
            if decision == "approved":
                po_name = move.target_purchase_order_id.display_name or (
                    picking.purchase_id.display_name if picking.purchase_id else ""
                )
                message = _(
                    "Extra product %(product)s (%(qty)s %(uom)s) was approved and linked to purchase order %(po)s.",
                    product=move.product_id.display_name,
                    qty=move.product_uom_qty,
                    uom=move.product_uom.name,
                    po=po_name,
                )
            else:
                message = _(
                    "Extra product %(product)s (%(qty)s %(uom)s) was rejected and removed from receipt %(picking)s.",
                    product=move.product_id.display_name,
                    qty=move.product_uom_qty,
                    uom=move.product_uom.name,
                    picking=picking.display_name,
                )
            picking.message_post(body=message, subtype_xmlid="mail.mt_note")

    def _check_is_purchase_manager(self):
        if not self.env.user.has_group("purchase.group_purchase_manager"):
            raise UserError(_("Only Purchase Managers can approve or reject extra products."))

    def _should_bypass_reservation(self, forced_location=False):
        if not self:
            return False
        return super()._should_bypass_reservation(forced_location=forced_location)

    def action_update_detail_operations(self):
        """Persist current edits and reload detailed operations popup."""
        self.ensure_one()
        return self.action_show_details()
