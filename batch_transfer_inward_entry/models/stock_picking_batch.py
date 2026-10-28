from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import format_list, float_is_zero


class StockPickingBatch(models.Model):
    _inherit = "stock.picking.batch"

    pending_extra_product_count = fields.Integer(
        compute="_compute_extra_product_counters",
        string="Pending Extra Products",
        store=True,
    )
    rejected_extra_product_count = fields.Integer(
        compute="_compute_extra_product_counters",
        string="Rejected Extra Products",
        store=True,
    )
    extra_validation_blocked = fields.Boolean(
        compute="_compute_extra_product_counters",
        string="Extra Product Approval Blocking",
        store=True,
    )
    purchase_order_ids = fields.Many2many(
        "purchase.order",
        compute="_compute_purchase_orders",
        string="Purchase Orders",
    )
    product_summary_ids = fields.One2many(
        "stock.picking.batch.product.summary",
        "batch_id",
        string="Products",
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        batches = super().create(vals_list)
        batches._sync_product_summaries()
        return batches

    def read(self, fields=None, load="_classic_read"):
        trigger = not fields or "product_summary_ids" in fields
        if trigger:
            self.sudo()._sync_product_summaries()
        return super().read(fields=fields, load=load)

    def write(self, vals):
        res = super().write(vals)
        if "picking_ids" in vals or self.env.context.get("batch_force_product_sync"):
            self._sync_product_summaries()
        return res

    def _sync_product_summaries(self):
        for batch in self:
            summary_map = {}
            moves = batch.move_ids.filtered(
                lambda m: m.state != "cancel"
                and m.picking_id
                and m.picking_id.picking_type_id.code in {"incoming", "internal", "outgoing"}
            )
            for move in moves:
                product = move.product_id
                if not product:
                    continue
                target_uom = product.uom_po_id or move.product_uom or product.uom_id
                key = (product.id, target_uom.id)
                demand = move.product_uom._compute_quantity(
                    move.product_uom_qty, target_uom, rounding_method="HALF-UP"
                )
                entry = summary_map.setdefault(
                    key,
                    {
                        "product": product,
                        "uom": target_uom,
                        "demand": 0.0,
                        "arrived": 0.0,
                        "rounding": target_uom.rounding or 0.0001,
                        "moves": self.env["stock.move"],
                    },
                )
                entry["demand"] += demand
                entry["arrived"] += move.product_uom._compute_quantity(
                    move.quantity, target_uom, rounding_method="HALF-UP"
                )
                entry["moves"] |= move

            existing = {
                (line.product_id.id, line.product_uom_id.id): line
                for line in batch.product_summary_ids
            }
            keep_lines = self.env["stock.picking.batch.product.summary"]

            for key, data in summary_map.items():
                summary_line = existing.pop(key, False)
                vals = {
                    "demand_qty": data["demand"],
                    "arrived_qty": data["arrived"],
                    "move_ids": [(6, 0, data["moves"].ids)],
                }
                if summary_line:
                    if float_is_zero(
                        data["arrived"], precision_rounding=data["rounding"]
                    ):
                        vals["arrived_qty"] = summary_line.arrived_qty
                    summary_line.with_context(batch_skip_arrived_update=True).write(vals)
                else:
                    vals.update(
                        {
                            "batch_id": batch.id,
                            "product_id": data["product"].id,
                            "product_uom_id": data["uom"].id,
                            "arrived_qty": 0.0,
                        }
                    )
                    summary_line = self.env["stock.picking.batch.product.summary"].create(vals)
                keep_lines |= summary_line

            if summary_map:
                (batch.product_summary_ids - keep_lines).unlink()


    @api.depends("move_ids.extra_product_state", "move_ids.purchase_line_id", "move_ids.picking_id.batch_id")
    def _compute_extra_product_counters(self):
        for batch in self:
            relevant_moves = batch.move_ids.filtered(
                lambda move: move.picking_id.picking_type_id.code in {"incoming", "internal"}
            )
            pending = relevant_moves.filtered(
                lambda m: m._requires_extra_product_approval()
                and m.extra_product_state in {"pending", "not_required"}
            )
            rejected = relevant_moves.filtered(lambda m: m.extra_product_state == "rejected")
            batch.pending_extra_product_count = len(pending)
            batch.rejected_extra_product_count = len(rejected)
            batch.extra_validation_blocked = bool(pending or rejected)

    @api.depends("picking_ids", "picking_ids.purchase_id")
    def _compute_purchase_orders(self):
        for batch in self:
            # Keep all related POs including RFQs so the wizard can propose them
            orders = batch.picking_ids.mapped("purchase_id").filtered(
                lambda po: po and po.state in ("draft", "sent", "to approve", "purchase", "done")
            )
            if not orders:
                # Fallback through moves relations if purchase_id is not set on internal pickings
                orders = batch.move_ids.mapped("purchase_line_id.order_id") | batch.move_ids.mapped(
                    "move_orig_ids.purchase_line_id.order_id"
                )
                orders = orders.filtered(lambda po: po and po.state in ("draft", "sent", "to approve", "purchase", "done"))
            batch.purchase_order_ids = orders

    def action_done(self):
        self._ensure_no_pending_extra_products()
        ctx = dict(self.env.context, allow_mixed_batch=True)
        res = super(StockPickingBatch, self.with_context(ctx)).action_done()
        self._rollover_batch_to_next_operation()
        return res

    def _rollover_batch_to_next_operation(self):
        for batch in self:
            if not batch.picking_ids:
                continue
            source_pickings = batch.picking_ids.filtered(lambda p: p.state == "done")
            
            if not source_pickings:
                continue
            dest_moves = source_pickings.mapped("move_ids").mapped("move_dest_ids")
            next_pickings = dest_moves.mapped("picking_id").filtered(
                lambda p: p and p.state not in ("done", "cancel")
            )

            if not next_pickings:
                next_pickings = self.env["stock.picking"].search(
                    [
                        ("state", "not in", ("done", "cancel")),
                        ("move_ids.move_orig_ids", "in", source_pickings.move_ids.ids),
                    ]
                )
            if not next_pickings:
                continue
            source_pickings.with_context(allow_mixed_batch=True).write({"batch_id": False})

            picking_types = next_pickings.mapped("picking_type_id")
            preferred_type = picking_types.sorted(key=lambda pt: (pt.code != "internal", pt.sequence))[:1]
            if preferred_type:
                assigned_pickings = next_pickings.filtered(lambda p: p.picking_type_id == preferred_type)
            else:
                assigned_pickings = next_pickings

            if not assigned_pickings:
                assigned_pickings = next_pickings

            assigned_pickings.with_context(allow_mixed_batch=True).write({"batch_id": batch.id})
            updates = {
                "picking_ids": [(6, 0, assigned_pickings.ids)],
                "state": "in_progress",
            }
            if preferred_type:
                updates["picking_type_id"] = preferred_type.id
            batch.with_context(batch_force_product_sync=True, allow_mixed_batch=True).write(updates)
            batch._prefill_next_pickings_lots(assigned_pickings)

    def _sanity_check(self):
        if self.env.context.get('allow_mixed_batch'):
            return
        return super()._sanity_check()

    def _ensure_no_pending_extra_products(self):
        for batch in self:
            moves = batch.move_ids.filtered(
                lambda move: move.picking_id.picking_type_id.code in {"incoming", "internal"}
            )
            newly_flagged = moves.filtered(
                lambda m: m._requires_extra_product_approval()
                and m.extra_product_state == "not_required"
            )
            if newly_flagged:
                newly_flagged._initialize_extra_product_state()
            blocking_moves = moves.filtered(
                lambda move: move._requires_extra_product_approval()
                and move.extra_product_state in {"pending", "rejected"}
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
                    "You must approve or remove the pending extra products before validating this batch:\n%s"
                )
                % product_names
            )

    def action_open_add_extra_move_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Add Extra Product"),
            "res_model": "add.extra.move.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_batch_id": self.id,
            },
        }

    def _bti_resolve_lot_for_product(self, product, lot_id=False, lot_name=False, company=False):
        lot = lot_id or self.env["stock.lot"]
        clean_name = (lot_name or "").strip()
        company = company or self.env.company
        if lot:
            return lot, False
        if product.tracking == "none" or not clean_name:
            return lot, clean_name or False
        lot_model = self.env["stock.lot"].sudo()
        existing_lot = lot_model.search(
            [
                ("name", "=", clean_name),
                ("product_id", "=", product.id),
                ("company_id", "in", [False, company.id]),
            ],
            order="company_id desc, id asc",
            limit=1,
        )
        if existing_lot:
            return existing_lot, False
        created_lot = lot_model.create(
            {
                "name": clean_name,
                "product_id": product.id,
                "company_id": company.id,
            }
        )
        return created_lot, False

    def _prefill_next_pickings_lots(self, pickings):
        MoveLine = self.env["stock.move.line"]
        for picking in pickings.filtered(lambda p: p.picking_type_id.code == "internal"):
            for move in picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel")):
                rounding = move.product_uom.rounding or move.product_uom.factor or 0.0001
                move.move_line_ids.unlink()
                vals_list = []
                lot_totals = {}
                for origin_move in move.move_orig_ids:
                    for line in origin_move.move_line_ids:
                        qty = getattr(line, "qty_done", line.quantity)
                        line_rounding = line.product_uom_id.rounding or line.product_uom_id.factor or 0.0001
                        if float_is_zero(qty, precision_rounding=line_rounding):
                            continue

                        qty_in_move_uom = line.product_uom_id._compute_quantity(
                            qty,
                            move.product_uom,
                            rounding_method="HALF-UP",
                        )
                        if float_is_zero(qty_in_move_uom, precision_rounding=rounding):
                            continue

                        lot, normalized_lot_name = self._bti_resolve_lot_for_product(
                            product=move.product_id,
                            lot_id=line.lot_id,
                            lot_name=line.lot_name,
                            company=move.company_id,
                        )
                        if move.product_id.tracking == "serial":
                            vals = move._prepare_move_line_vals(quantity=qty_in_move_uom)
                            vals.update(
                                {
                                    "lot_id": lot.id if lot else False,
                                    "lot_name": (
                                        lot.display_name if lot else normalized_lot_name
                                    ),
                                }
                            )
                            vals_list.append(vals)
                            continue

                        key = (lot.id or 0, normalized_lot_name or "")
                        lot_totals[key] = lot_totals.get(key, 0.0) + qty_in_move_uom

                for (lot_id, lot_name), total_qty in lot_totals.items():
                    if float_is_zero(total_qty, precision_rounding=rounding):
                        continue
                    vals = move._prepare_move_line_vals(quantity=total_qty)
                    lot_record = self.env["stock.lot"].browse(lot_id).exists() if lot_id else self.env["stock.lot"]
                    vals.update(
                        {
                            "lot_id": lot_id or False,
                            "lot_name": (lot_record.display_name if lot_record else lot_name) or False,
                        }
                    )
                    vals_list.append(vals)
                if vals_list:
                    MoveLine.create(vals_list)

class StockPickingBatchProductSummary(models.Model):
    _name = "stock.picking.batch.product.summary"
    _description = "Batch Purchase Product Summary"
    _order = "product_id"

    batch_id = fields.Many2one(
        "stock.picking.batch",
        string="Batch",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        ondelete="restrict",
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="UoM",
        required=True,
        ondelete="restrict",
        readonly=True,
    )
    demand_qty = fields.Float(
        string="Demand Quantity",
        digits="Product Unit of Measure",
        readonly=True,
    )
    arrived_qty = fields.Float(
        string="Arrived Quantity",
        digits="Product Unit of Measure",
        default=0.0,
    )
    move_ids = fields.Many2many(
        "stock.move",
        "stock_batch_product_summary_move_rel",
        "summary_id",
        "move_id",
        string="Related Moves",
        readonly=True,
    )
    extra_product_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("pending", "Pending Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Extra Product Approval",
        compute="_compute_extra_product_info",
        readonly=True,
        store=False,
    )
    extra_product_requested_on = fields.Datetime(
        string="Requested On",
        compute="_compute_extra_product_info",
        readonly=True,
    )
    extra_product_requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        compute="_compute_extra_product_info",
        readonly=True,
    )
    target_purchase_order_display = fields.Char(
        string="Target Purchase Orders",
        compute="_compute_extra_product_info",
        readonly=True,
    )
    extra_has_pending = fields.Boolean(
        string="Has Pending Extra Product",
        compute="_compute_extra_product_info",
        readonly=True,
    )

    def action_open_detail_operations(self):
        self.ensure_one()
        wizard = self.env["batch.detail.operations.wizard"].with_context(
            active_id=self.id, default_summary_id=self.id
        ).create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("Detailed Operations"),
            "res_model": "batch.detail.operations.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    @api.depends(
        "move_ids.extra_product_state",
        "move_ids.extra_product_requested_on",
        "move_ids.extra_product_requested_by_id",
        "move_ids.target_purchase_order_id",
    )
    def _compute_extra_product_info(self):
        for summary in self:
            extra_moves = summary.move_ids.filtered(
                lambda move: move.extra_product_state and move.extra_product_state != "not_required"
            )
            if not extra_moves:
                summary.extra_product_state = "not_required"
                summary.extra_product_requested_on = False
                summary.extra_product_requested_by_id = False
                summary.target_purchase_order_display = False
                summary.extra_has_pending = False
                continue

            states = extra_moves.mapped("extra_product_state")
            if "pending" in states:
                state = "pending"
            elif "rejected" in states:
                state = "rejected"
            elif "approved" in states:
                state = "approved"
            else:
                state = "not_required"
            summary.extra_product_state = state
            summary.extra_has_pending = "pending" in states

            request_moves = extra_moves.filtered("extra_product_requested_on")
            reference_move = request_moves and request_moves.sorted(
                key=lambda m: m.extra_product_requested_on
            )[0] or extra_moves[0]
            summary.extra_product_requested_on = reference_move.extra_product_requested_on
            summary.extra_product_requested_by_id = reference_move.extra_product_requested_by_id

            po_names = [
                po.display_name
                for po in extra_moves.mapped("target_purchase_order_id")
                if po
            ]
            if po_names:
                unique_names = list(dict.fromkeys(po_names))
                summary.target_purchase_order_display = ", ".join(unique_names)
            else:
                summary.target_purchase_order_display = False

    def write(self, vals):
        if "arrived_qty" in vals and not self.env.context.get("batch_skip_arrived_update"):
            target_qty = vals["arrived_qty"]
            for line in self:
                line._apply_arrived_qty(target_qty)
            return True
        return super().write(vals)

    def _apply_arrived_qty(self, target_qty):
        self.ensure_one()
        moves = self.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        if not moves:
            return
        target_uom = self.product_uom_id or self.product_id.uom_po_id or self.product_id.uom_id

        def _sort_key(move):
            order = move.purchase_line_id.order_id if move.purchase_line_id else False
            return (
                order.date_order if order else move.create_date,
                order.id if order else 0,
                move.purchase_line_id.id if move.purchase_line_id else 0,
                move.id,
            )

        ordered_moves = sorted(moves, key=_sort_key)
        demand_totals = [
            move.product_uom._compute_quantity(move.product_uom_qty, target_uom, rounding_method="HALF-UP")
            for move in ordered_moves
        ]
        total_demand = sum(demand_totals)
        if float_is_zero(total_demand, precision_rounding=target_uom.rounding or 0.0001):
            demand_totals = [1.0] * len(ordered_moves)
            total_demand = float(len(ordered_moves))

        remaining = target_qty
        assigned = []
        for demand in demand_totals:
            assign = min(remaining, demand)
            assigned.append(assign)
            remaining -= assign
        if not float_is_zero(remaining, precision_rounding=target_uom.rounding or 0.0001) and assigned:
            assigned[-1] += remaining
            remaining = 0.0

        self.with_context(batch_skip_arrived_update=True).write({"arrived_qty": target_qty})
        residual_context = dict(self.env.context, batch_skip_summary_sync=True)
        StockMoveLine = self.env["stock.move.line"]
        for move, target_amount in zip(ordered_moves, assigned):
            target_qty_in_move_uom = target_uom._compute_quantity(
                target_amount, move.product_uom, rounding_method="HALF-UP"
            )
            if float_is_zero(
                target_qty_in_move_uom,
                precision_rounding=move.product_uom.rounding or move.product_uom.factor or 0.0001,
            ):
                continue

            move.with_context(residual_context)._set_quantity_done(target_qty_in_move_uom)

            existing_lines = move.move_line_ids.filtered(
                lambda ml: float_is_zero(
                    getattr(ml, "qty_done", ml.quantity),
                    precision_rounding=ml.product_uom_id.rounding or ml.product_uom_id.factor or 0.0001,
                )
            )
            leftover = target_qty_in_move_uom - sum(
                getattr(line, "qty_done", line.quantity) for line in existing_lines
            )
            if leftover > 0 and not move.move_line_ids.filtered(
                lambda ml: not float_is_zero(
                    getattr(ml, "qty_done", ml.quantity),
                    precision_rounding=ml.product_uom_id.rounding or ml.product_uom_id.factor or 0.0001,
                )
            ):
                line_vals = move._prepare_move_line_vals(quantity=target_qty_in_move_uom)
                line_vals.update({"lot_id": False, "lot_name": False})
                StockMoveLine.create(line_vals)

        total_done = sum(move.quantity for move in moves)
        remaining_qty = target_qty - target_uom._compute_quantity(total_done, target_uom, rounding_method="HALF-UP")
        if not float_is_zero(remaining_qty, precision_rounding=target_uom.rounding or 0.0001):
            last_move = ordered_moves[-1]
            adjust_qty = last_move.product_uom._compute_quantity(
                target_uom._compute_quantity(remaining_qty, last_move.product_uom, rounding_method="HALF-UP"),
                last_move.product_uom,
                rounding_method="HALF-UP",
            )
            new_qty = last_move.quantity + adjust_qty
            last_move.with_context(residual_context)._set_quantity_done(new_qty)

        self.batch_id.with_context(batch_force_product_sync=True)._sync_product_summaries()

    def _refresh_from_moves(self):
        target_uom = self.product_uom_id or self.product_id.uom_po_id or self.product_id.uom_id
        demand = sum(
            move.product_uom._compute_quantity(move.product_uom_qty, target_uom, rounding_method="HALF-UP")
            for move in self.move_ids
        )
        arrived = sum(
            move.product_uom._compute_quantity(move.quantity, target_uom, rounding_method="HALF-UP")
            for move in self.move_ids
        )
        if float_is_zero(arrived, precision_rounding=target_uom.rounding or 0.0001):
            arrived = self.arrived_qty
        super(
            StockPickingBatchProductSummary,
            self.with_context(batch_skip_arrived_update=True),
        ).write({"demand_qty": demand, "arrived_qty": arrived})

    def action_summary_approve_extra_product(self):
        pending_moves = self.move_ids.filtered(lambda move: move.extra_product_state == "pending")
        if pending_moves:
            pending_moves.action_approve_extra_product()
        return True

    def action_summary_reject_extra_product(self):
        pending_moves = self.move_ids.filtered(lambda move: move.extra_product_state == "pending")
        if pending_moves:
            pending_moves.action_reject_extra_product()
        return True








