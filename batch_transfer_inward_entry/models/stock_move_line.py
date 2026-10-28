from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_is_zero


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    lot_display_name = fields.Char(
        string="Lot/Serial Number",
        compute="_compute_lot_display_name",
    )
    extra_product_state = fields.Selection(
        related="move_id.extra_product_state", readonly=True
    )
    extra_product_requested_on = fields.Datetime(
        related="move_id.extra_product_requested_on", readonly=True
    )
    extra_product_requested_by_id = fields.Many2one(
        "res.users", related="move_id.extra_product_requested_by_id", readonly=True
    )
    target_purchase_order_id = fields.Many2one(
        "purchase.order", related="move_id.target_purchase_order_id", readonly=False
    )
    available_target_purchase_order_ids = fields.Many2many(
        "purchase.order", compute="_compute_available_target_pos"
    )
    bti_is_lot_summary_leader = fields.Boolean(
        string="Summary Leader",
        compute="_compute_bti_lot_summary_fields",
    )
    bti_lot_summary_qty = fields.Float(
        string="Quantity",
        digits="Product Unit of Measure",
        compute="_compute_bti_lot_summary_fields",
    )

    @api.depends("lot_name", "lot_id")
    def _compute_lot_display_name(self):
        for line in self:
            line.lot_display_name = line.lot_name or (
                line.lot_id.display_name if line.lot_id else False
            )

    @api.depends("move_id", "move_id.available_target_purchase_order_ids")
    def _compute_available_target_pos(self):
        for line in self:
            line.available_target_purchase_order_ids = (
                line.move_id.available_target_purchase_order_ids
            )

    @staticmethod
    def _bti_lot_group_key(line):
        lot_name = (line.lot_name or "").strip().lower()
        return (
            line.picking_id.id or 0,
            line.product_id.id or 0,
            line.lot_id.id or 0,
            lot_name,
            line.location_dest_id.id or 0,
        )

    @staticmethod
    def _bti_line_order_key(line):
        """Return a stable comparable key for persisted and unsaved lines."""
        line_id = line.id
        if isinstance(line_id, int):
            return (0, line_id)
        # NewId (unsaved onchange rows): fallback to Python object identity
        return (1, id(line))

    @api.depends(
        "picking_id",
        "picking_id.move_line_ids.product_id",
        "picking_id.move_line_ids.lot_id",
        "picking_id.move_line_ids.lot_name",
        "picking_id.move_line_ids.location_dest_id",
        "picking_id.move_line_ids.product_uom_id",
        "picking_id.move_line_ids.quantity",
    )
    def _compute_bti_lot_summary_fields(self):
        for line in self:
            line.bti_is_lot_summary_leader = False
            line.bti_lot_summary_qty = 0.0

        lines_by_picking = defaultdict(lambda: self.env["stock.move.line"])
        picking_map = {}
        for line in self.filtered("picking_id"):
            lines_by_picking[line.picking_id.id] |= line
            picking_map[line.picking_id.id] = line.picking_id

        for picking_id in lines_by_picking:
            picking = picking_map[picking_id]
            grouped = {}
            for line in picking.move_line_ids.sorted(key=self._bti_line_order_key):
                if not line.product_id:
                    continue
                rounding = line.product_uom_id.rounding or line.product_id.uom_id.rounding or 0.0001
                if float_is_zero(line.quantity, precision_rounding=rounding):
                    continue
                key = self._bti_lot_group_key(line)
                bucket = grouped.setdefault(
                    key,
                    {
                        "leader": line,
                        "lines": self.env["stock.move.line"],
                    },
                )
                if self._bti_line_order_key(line) < self._bti_line_order_key(bucket["leader"]):
                    bucket["leader"] = line
                bucket["lines"] |= line

            for bucket in grouped.values():
                leader = bucket["leader"]
                lines = bucket["lines"]
                summary_uom = leader.product_id.uom_id or leader.product_uom_id
                total_summary_qty = 0.0
                for row in lines:
                    source_uom = row.product_uom_id or summary_uom
                    total_summary_qty += source_uom._compute_quantity(
                        row.quantity,
                        summary_uom,
                        rounding_method="HALF-UP",
                    )

                if leader in self:
                    leader_uom = leader.product_uom_id or summary_uom
                    leader.bti_is_lot_summary_leader = True
                    leader.bti_lot_summary_qty = summary_uom._compute_quantity(
                        total_summary_qty,
                        leader_uom,
                        rounding_method="HALF-UP",
                    )

    @api.onchange("available_target_purchase_order_ids")
    def _onchange_available_target_purchase_orders(self):
        values = self.available_target_purchase_order_ids.ids
        domain = [("id", "in", values)] if values else []
        if self.target_purchase_order_id and self.target_purchase_order_id.id not in values:
            self.target_purchase_order_id = False
        return {"domain": {"target_purchase_order_id": domain}}

    def action_move_line_approve(self):
        moves = self.mapped("move_id")
        if moves:
            moves.action_approve_extra_product()

    def action_move_line_reject(self):
        moves = self.mapped("move_id")
        if moves:
            moves.action_reject_extra_product()

    @api.model_create_multi
    def create(self, vals_list):
        if vals_list:
            lot_ids = {
                vals.get("lot_id")
                for vals in vals_list
                if vals.get("lot_id") and not vals.get("lot_name")
            }
            lot_name_by_id = {}
            if lot_ids:
                for lot in self.env["stock.lot"].browse(list(lot_ids)).exists():
                    lot_name_by_id[lot.id] = lot.display_name or lot.name

            prepared_vals_list = []
            for vals in vals_list:
                if vals.get("lot_id") and not vals.get("lot_name"):
                    lot_name = lot_name_by_id.get(vals["lot_id"])
                    if lot_name:
                        vals = dict(vals)
                        vals["lot_name"] = lot_name
                prepared_vals_list.append(vals)
            vals_list = prepared_vals_list

        lines = super().create(vals_list)
        if not self.env.context.get("batch_skip_summary_sync"):
            batches = lines.mapped("picking_id.batch_id")
            if batches:
                batches.with_context(batch_force_product_sync=True)._sync_product_summaries()
        return lines

    def write(self, vals):
        if vals.get("lot_id") and not vals.get("lot_name"):
            lot = self.env["stock.lot"].browse(vals["lot_id"]).exists()
            if lot:
                vals = dict(vals)
                vals["lot_name"] = lot.display_name or lot.name
        res = super().write(vals)
        if not self.env.context.get("batch_skip_summary_sync"):
            batches = self.mapped("picking_id.batch_id")
            if batches:
                batches.with_context(batch_force_product_sync=True)._sync_product_summaries()
        return res

    def unlink(self):
        batches = self.mapped("picking_id.batch_id")
        res = super().unlink()
        if batches and not self.env.context.get("batch_skip_summary_sync"):
            batches.with_context(batch_force_product_sync=True)._sync_product_summaries()
        return res
