from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    batch_extra_move_ids = fields.Many2many(
        "stock.move",
        compute="_compute_batch_extra_moves",
        string="Batch Extra Products",
    )
    batch_extra_move_ids_pending = fields.Many2many(
        "stock.move",
        compute="_compute_batch_extra_moves",
        string="Pending Batch Extra Products",
    )
    batch_pending_extra_move_count = fields.Integer(
        compute="_compute_batch_extra_moves",
        string="Pending Extra Products",
    )
    batch_extra_product_activity_state = fields.Selection(
        [
            ("pending", "Approval Required"),
            ("approved", "Change Approved"),
        ],
        compute="_compute_batch_extra_moves",
        string="Activities",
        readonly=True,
    )

    @api.depends_context("uid")
    def _compute_batch_extra_moves(self):
        StockMove = self.env["stock.move"]
        domain = [
            ("target_purchase_order_id", "in", self.ids),
            ("extra_product_state", "!=", "not_required"),
        ]
        moves = StockMove.search(domain)
        moves_by_order = {order_id: StockMove.browse() for order_id in self.ids}
        for move in moves:
            order_id = move.target_purchase_order_id.id
            if not order_id:
                continue
            moves_by_order[order_id] |= move
        for order in self:
            order_moves = moves_by_order.get(order.id, StockMove.browse())
            order.batch_extra_move_ids = order_moves
            pending = order_moves.filtered(lambda move: move.extra_product_state == "pending")
            order.batch_extra_move_ids_pending = pending
            order.batch_pending_extra_move_count = len(pending)
            if pending:
                order.batch_extra_product_activity_state = "pending"
            elif order_moves:
                order.batch_extra_product_activity_state = "approved"
            else:
                order.batch_extra_product_activity_state = False
