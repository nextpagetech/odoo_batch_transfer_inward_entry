from odoo import api, fields, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    product_template_attribute_value_ids = fields.Many2many(
        comodel_name="product.template.attribute.value",
        compute="_compute_product_template_attribute_value_ids",
        store=True,
        readonly=True,
    )

    @api.depends("product_id", "product_id.product_template_attribute_value_ids")
    def _compute_product_template_attribute_value_ids(self):
        for quant in self:
            quant.product_template_attribute_value_ids = (
                quant.product_id.product_template_attribute_value_ids
            )
