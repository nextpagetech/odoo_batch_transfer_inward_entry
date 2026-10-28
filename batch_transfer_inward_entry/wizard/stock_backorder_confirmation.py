from odoo import models


class StockBackorderConfirmation(models.TransientModel):
    _inherit = "stock.backorder.confirmation"

    def _bti_pickings_to_validate(self):
        picking_ids = self.env.context.get("button_validate_picking_ids") or []
        pickings = self.env["stock.picking"].browse(picking_ids)
        if pickings:
            return pickings
        return self.backorder_confirmation_line_ids.mapped("picking_id") | self.pick_ids

    def _bti_rollover_done_batches(self, pickings):
        batches = pickings.filtered(lambda p: p.state == "done" and p.batch_id).mapped("batch_id")
        if batches:
            batches.with_context(allow_mixed_batch=True)._rollover_batch_to_next_operation()

    def process(self):
        pickings = self._bti_pickings_to_validate()
        res = super().process()
        self._bti_rollover_done_batches(pickings)
        return res

    def process_cancel_backorder(self):
        pickings = self._bti_pickings_to_validate()
        res = super().process_cancel_backorder()
        self._bti_rollover_done_batches(pickings)
        return res
