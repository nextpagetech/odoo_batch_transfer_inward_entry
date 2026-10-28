from odoo import fields, models


class StockPickingShortfall(models.Model):
    _name = "stock.picking.shortfall"
    _description = "Pending Backorder Shortfall"

    picking_id = fields.Many2one(
        "stock.picking",
        string="Picking",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        ondelete="restrict",
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="UoM",
        required=True,
        ondelete="restrict",
    )
    quantity = fields.Float(
        string="Shortfall Quantity",
        digits="Product Unit of Measure",
        required=True,
    )
    purchase_line_id = fields.Many2one(
        "purchase.order.line",
        string="Purchase Order Line",
        ondelete="set null",
    )
