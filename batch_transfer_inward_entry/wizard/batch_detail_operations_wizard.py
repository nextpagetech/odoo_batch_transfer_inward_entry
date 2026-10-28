from odoo import api, fields, models, _
from odoo.tools import float_is_zero
from odoo.exceptions import ValidationError


class BatchDetailOperationsWizard(models.TransientModel):
    _name = "batch.detail.operations.wizard"
    _description = "Batch Detail Operations Wizard"

    summary_id = fields.Many2one(
        "stock.picking.batch.product.summary",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(related="summary_id.product_id", readonly=True)
    product_uom_id = fields.Many2one(related="summary_id.product_uom_id", readonly=True)
    arrived_qty = fields.Float(related="summary_id.arrived_qty", readonly=True)
    demand_qty = fields.Float(related="summary_id.demand_qty", readonly=True, string="Demand")
    product_uom_qty = fields.Float(related="summary_id.demand_qty", readonly=True)
    total_qty = fields.Float(
        compute="_compute_total_qty",
        readonly=True,
        string="Total Quantity",
    )
    picking_code = fields.Selection(
        selection=[
            ("incoming", "Receipts"),
            ("outgoing", "Delivery"),
            ("internal", "Internal Transfer"),
        ],
        compute="_compute_defaults",
        readonly=True,
    )
    default_location_id = fields.Many2one("stock.location", compute="_compute_defaults")
    default_location_dest_id = fields.Many2one("stock.location", compute="_compute_defaults")
    default_product_uom_id = fields.Many2one("uom.uom", compute="_compute_defaults")
    show_quant = fields.Boolean(compute="_compute_defaults")
    move_line_ids = fields.One2many(
        "batch.detail.operations.wizard.line",
        "wizard_id",
        string="Operations",
    )

    @staticmethod
    def _fifo_sort_key(move):
        order = move.purchase_line_id.order_id if move.purchase_line_id else False
        return (
            order.date_order if order else move.create_date,
            order.id if order else 0,
            move.purchase_line_id.id if move.purchase_line_id else 0,
            move.id,
        )

    @api.depends(
        "move_line_ids.quantity",
        "move_line_ids.product_uom_id",
        "summary_id.product_uom_id",
        "summary_id.product_id",
    )
    def _compute_total_qty(self):
        for wizard in self:
            summary_uom = wizard.summary_id.product_uom_id or wizard.summary_id.product_id.uom_id
            total = 0.0
            for line in wizard.move_line_ids:
                line_uom = line.product_uom_id or summary_uom
                total += line_uom._compute_quantity(
                    line.quantity, summary_uom, rounding_method="HALF-UP"
                )
            wizard.total_qty = total

    @api.depends("summary_id")
    def _compute_defaults(self):
        for wizard in self:
            move = wizard.summary_id.move_ids[:1]
            wizard.picking_code = move.picking_code if move else False
            wizard.show_quant = bool(move and move.picking_code != "incoming")
            wizard.default_location_id = move.location_id if move else False
            wizard.default_location_dest_id = move.location_dest_id if move else False
            wizard.default_product_uom_id = (
                wizard.summary_id.product_uom_id or wizard.summary_id.product_id.uom_id
            )

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        summary = self.env["stock.picking.batch.product.summary"].browse(
            self.env.context.get("active_id")
        )
        summary_uom = summary.product_uom_id or summary.product_id.uom_id
        result["summary_id"] = summary.id
        raw_entries = []
        for move in sorted(summary.move_ids, key=self._fifo_sort_key):
            for move_line in move.move_line_ids:
                lot_text = (move_line.lot_name or "").strip()
                if not lot_text and move_line.lot_id:
                    lot_text = move_line.lot_id.display_name or move_line.lot_id.name or ""
                qty = move_line.product_uom_id._compute_quantity(
                    move_line.quantity, summary_uom, rounding_method="HALF-UP"
                )
                raw_entries.append(
                    {
                        "lot_id": move_line.lot_id.id,
                        "lot_name": lot_text,
                        "location_id": move_line.location_id.id,
                        "location_dest_id": move_line.location_dest_id.id,
                        "quantity": qty,
                    }
                )

        lines = []
        grouped = {}
        for entry in raw_entries:
            key = (
                entry["lot_id"] or 0,
                (entry["lot_name"] or "").lower(),
                entry["location_id"] or 0,
                entry["location_dest_id"] or 0,
            )
            bucket = grouped.setdefault(
                key,
                {
                    "lot_id": entry["lot_id"] or False,
                    "lot_name": entry["lot_name"] or False,
                    "location_id": entry["location_id"] or False,
                    "location_dest_id": entry["location_dest_id"] or False,
                    "quantity": 0.0,
                },
            )
            bucket["quantity"] += entry["quantity"]

        for data in sorted(
            grouped.values(),
            key=lambda row: (
                row["lot_name"] or "",
                row["lot_id"] or 0,
                row["location_id"] or 0,
                row["location_dest_id"] or 0,
            ),
        ):
            lines.append(
                (
                    0,
                    0,
                    {
                        # Grouped rows represent one-or-many backend move lines.
                        "move_line_id": False,
                        "move_id": False,
                        "lot_id": data["lot_id"],
                        "lot_name": data["lot_name"],
                        "location_id": data["location_id"],
                        "location_dest_id": data["location_dest_id"],
                        "quantity": data["quantity"],
                        "product_uom_id": summary_uom.id,
                    },
                )
            )

        picking_code = summary.move_ids[:1].picking_code if summary.move_ids else False
        if not lines and picking_code == "incoming":
            default_dest = summary.move_ids[:1].location_dest_id.id if summary.move_ids else False
            lines.append(
                (
                    0,
                    0,
                    {
                        "move_line_id": False,
                        "move_id": False,
                        "lot_id": False,
                        "lot_name": False,
                        "location_id": summary.move_ids[:1].location_id.id if summary.move_ids else False,
                        "location_dest_id": default_dest,
                        "quantity": summary.arrived_qty,
                        "product_uom_id": summary_uom.id,
                    },
                )
            )
        result["move_line_ids"] = lines
        return result

    def _collect_entries(self):
        summary_uom = self.summary_id.product_uom_id or self.summary_id.product_id.uom_id
        product = self.summary_id.product_id
        company = (
            self.summary_id.batch_id.company_id
            or self.summary_id.move_ids[:1].company_id
            or self.env.company
        )
        entries = []
        total_qty = 0.0
        for line in self.move_line_ids:
            qty = (line.product_uom_id or summary_uom)._compute_quantity(
                line.quantity, summary_uom, rounding_method="HALF-UP"
            )
            total_qty += qty
            preferred_move = line.move_id or (line.move_line_id.move_id if line.move_line_id else False)
            lot_id, lot_name = self._resolve_lot_for_entry(
                product=product,
                lot=line.lot_id,
                lot_name=line.lot_name,
                company=company,
            )
            entries.append(
                {
                    "qty": qty,
                    "lot_id": lot_id,
                    "lot_name": lot_name,
                    "location_dest_id": line.location_dest_id,
                    "product_uom": line.product_uom_id or summary_uom,
                    "preferred_move": preferred_move,
                }
            )
        return entries, total_qty

    def _resolve_lot_for_entry(self, product, lot, lot_name, company):
        lot_name = (lot_name or "").strip()
        if lot:
            return lot, False
        if product.tracking == "none" or not lot_name:
            return False, lot_name or False
        lot_model = self.env["stock.lot"].sudo()
        existing_lot = lot_model.search(
            [
                ("name", "=", lot_name),
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
                "name": lot_name,
                "product_id": product.id,
                "company_id": company.id,
            }
        )
        return created_lot, False

    def _create_move_line(self, move, allocation, qty_summary_uom, summary_uom):
        qty_move_uom = summary_uom._compute_quantity(
            qty_summary_uom, move.product_uom, rounding_method="HALF-UP"
        )
        qty_line_uom = summary_uom._compute_quantity(
            qty_summary_uom, allocation["product_uom"], rounding_method="HALF-UP"
        )
        vals = move._prepare_move_line_vals(quantity=qty_move_uom)
        vals.update(
            {
                "lot_id": allocation["lot_id"].id if allocation["lot_id"] else False,
                "lot_name": (
                    allocation["lot_id"].display_name
                    if allocation["lot_id"]
                    else allocation["lot_name"]
                ),
                "location_dest_id": (
                    allocation["location_dest_id"].id
                    if allocation["location_dest_id"]
                    else move.location_dest_id.id
                ),
                "product_uom_id": allocation["product_uom"].id,
                "quantity": qty_line_uom,
            }
        )
        return vals

    def _allocate_for_move(self, move, capacity_summary_uom, queue, summary_uom, precision):
        allocations = []
        for preferred in (True, False):
            idx = 0
            while idx < len(queue) and capacity_summary_uom > precision:
                entry = queue[idx]
                if preferred and entry["preferred_move"] and entry["preferred_move"] != move:
                    idx += 1
                    continue
                assign = min(capacity_summary_uom, entry["qty"])
                if float_is_zero(assign, precision_rounding=precision):
                    queue.pop(idx)
                    continue
                allocations.append((entry, assign))
                capacity_summary_uom -= assign
                entry["qty"] -= assign
                if float_is_zero(entry["qty"], precision_rounding=precision):
                    queue.pop(idx)
                else:
                    idx += 1
            if capacity_summary_uom <= precision:
                break
        return allocations, capacity_summary_uom

    def _apply_allocations(self):
        self.ensure_one()
        summary = self.summary_id
        summary_uom = summary.product_uom_id or summary.product_id.uom_id
        precision = summary_uom.rounding or 0.0001

        entries, total_qty = self._collect_entries()

        # Enforce unique lot/serial per product within this batch product summary.
        seen = set()
        for entry in entries:
            lot_label = entry["lot_id"].name if entry["lot_id"] else entry["lot_name"]
            if not lot_label:
                continue
            key = (self.summary_id.product_id.id, lot_label.strip().lower())
            if key in seen:
                raise ValidationError(
                    _(
                        "Lot '%(lot)s' is already used for %(product)s in this batch transfer.",
                        lot=lot_label,
                        product=self.summary_id.product_id.display_name,
                    )
                )
            seen.add(key)

        summary.with_context(batch_skip_arrived_update=True).write({"arrived_qty": total_qty})

        moves = summary.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        ordered_moves = sorted(moves, key=self._fifo_sort_key)
        move_data = []
        for move in ordered_moves:
            demand_qty = summary_uom._compute_quantity(
                move.product_uom_qty, summary_uom, rounding_method="HALF-UP"
            )
            move_data.append({"move": move, "capacity": demand_qty})

        moves.move_line_ids.unlink()
        ctx = dict(self.env.context, batch_skip_summary_sync=True)
        StockMoveLine = self.env["stock.move.line"]
        queue = entries[:]
        assigned_summary_by_move = {data["move"].id: 0.0 for data in move_data}

        for data in move_data:
            move = data["move"]
            capacity = data["capacity"]
            allocations, capacity = self._allocate_for_move(
                move, capacity, queue, summary_uom, precision
            )
            for entry, qty in allocations:
                vals = self._create_move_line(move, entry, qty, summary_uom)
                StockMoveLine.create(vals)
                assigned_summary_by_move[move.id] += qty

        if queue and move_data:
            last_move = move_data[-1]["move"]
            for entry in queue:
                qty = entry["qty"]
                if float_is_zero(qty, precision_rounding=precision):
                    continue
                vals = self._create_move_line(last_move, entry, qty, summary_uom)
                StockMoveLine.create(vals)
                assigned_summary_by_move[last_move.id] += qty

        for data in move_data:
            move = data["move"]
            target_summary_qty = assigned_summary_by_move.get(move.id, 0.0)
            target_move_qty = summary_uom._compute_quantity(
                target_summary_qty, move.product_uom, rounding_method="HALF-UP"
            )
            move.with_context(ctx)._set_quantity_done(target_move_qty)

        summary.batch_id.with_context(batch_force_product_sync=True)._sync_product_summaries()
        return summary

    def action_apply(self):
        self._apply_allocations()
        return {"type": "ir.actions.act_window_close"}

    def action_update(self):
        summary = self._apply_allocations()
        refresh_vals = self.with_context(active_id=summary.id).default_get(["move_line_ids"])
        self.write(
            {
                "move_line_ids": [(5, 0, 0)] + (refresh_vals.get("move_line_ids") or []),
            }
        )
        view = self.env.ref("batch_transfer_inward_entry.view_batch_detail_operations_wizard")
        return {
            "name": _("Detailed Operations"),
            "type": "ir.actions.act_window",
            "res_model": "batch.detail.operations.wizard",
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "res_id": self.id,
            "context": dict(self.env.context, active_id=summary.id),
        }


class BatchDetailOperationsWizardLine(models.TransientModel):
    _name = "batch.detail.operations.wizard.line"
    _description = "Batch Detail Operations Wizard Line"

    wizard_id = fields.Many2one(
        "batch.detail.operations.wizard",
        required=True,
        ondelete="cascade",
    )
    move_line_id = fields.Many2one("stock.move.line", string="Existing Move Line")
    move_id = fields.Many2one("stock.move", string="Transfer Line")
    product_id = fields.Many2one(related="wizard_id.product_id", readonly=True)
    location_id = fields.Many2one(
        "stock.location",
        string="From",
        domain="[('usage', '!=', 'view')]",
        default=lambda self: self.env.context.get("default_location_id"),
    )
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial Number")
    lot_name = fields.Char(string="Lot/Serial Number")
    quant_id = fields.Many2one("stock.quant", string="Stock Details")
    package_id = fields.Many2one("stock.quant.package", string="Source Package")
    owner_id = fields.Many2one("res.partner", string="Owner")
    location_dest_id = fields.Many2one(
        "stock.location",
        string="Store To",
        domain="[('usage', '!=', 'view')]",
        default=lambda self: self.env.context.get("default_location_dest_id"),
    )
    quantity = fields.Float(string="Quantity", digits="Product Unit of Measure", required=True, default=0.0)
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="UoM",
        default=lambda self: self.env.context.get("default_product_uom_id"),
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        quant_id = self.env.context.get("default_quant_id")
        if not quant_id:
            return res
        quant = self.env["stock.quant"].browse(quant_id).exists()
        if not quant:
            return res
        res.setdefault("quant_id", quant.id)
        res.setdefault("location_id", quant.location_id.id)
        res.setdefault("lot_id", quant.lot_id.id if quant.lot_id else False)
        res.setdefault("package_id", quant.package_id.id if quant.package_id else False)
        res.setdefault("owner_id", quant.owner_id.id if quant.owner_id else False)
        if quant.lot_id:
            res.setdefault("lot_name", quant.lot_id.display_name or quant.lot_id.name)
        if "default_quantity" in self.env.context:
            res["quantity"] = self.env.context.get("default_quantity") or 0.0
        return res

    @api.onchange("quant_id")
    def _onchange_quant_id(self):
        for line in self:
            quant = line.quant_id
            if not quant:
                continue
            line.location_id = quant.location_id
            line.lot_id = quant.lot_id
            line.package_id = quant.package_id
            line.owner_id = quant.owner_id
            line.lot_name = (
                quant.lot_id.display_name
                if quant.lot_id
                else (line.lot_name or False)
            )
            summary_uom = (
                line.wizard_id.summary_id.product_uom_id
                or line.wizard_id.summary_id.product_id.uom_id
            )
            line_uom = line.product_uom_id or summary_uom
            qty_summary = line.product_id.uom_id._compute_quantity(
                quant.available_quantity, summary_uom, rounding_method="HALF-UP"
            )
            already_assigned = 0.0
            for other in line.wizard_id.move_line_ids:
                if other == line:
                    continue
                other_uom = other.product_uom_id or summary_uom
                already_assigned += other_uom._compute_quantity(
                    other.quantity, summary_uom, rounding_method="HALF-UP"
                )
            remaining = max((line.wizard_id.product_uom_qty or 0.0) - already_assigned, 0.0)
            default_summary_qty = min(qty_summary, remaining) if remaining > 0 else 0.0
            line.quantity = summary_uom._compute_quantity(
                default_summary_qty, line_uom, rounding_method="HALF-UP"
            )

    def action_open_move_line(self):
        self.ensure_one()
        if not self.move_line_id:
            return False
        view = self.env.ref('stock.view_move_line_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock Move Line'),
            'res_model': 'stock.move.line',
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'res_id': self.move_line_id.id,
            'target': 'current',
        }
