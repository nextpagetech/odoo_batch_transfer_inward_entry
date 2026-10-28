from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    product_template_id = fields.Many2one(
        comodel_name="product.template",
        string="Product Template",
        compute="_compute_product_template_id",
        readonly=False,
        search="_search_product_template_id",
        domain=[("purchase_ok", "=", True)],
    )
    is_configurable_product = fields.Boolean(
        string="Is the product configurable?",
        related="product_template_id.has_configurable_attributes",
        depends=["product_id"],
    )
    product_custom_attribute_value_ids = fields.One2many(
        comodel_name="product.attribute.custom.value",
        inverse_name="purchase_order_line_id",
        string="Custom Values",
        copy=True,
    )

    @api.depends("product_id")
    def _compute_product_template_id(self):
        for line in self:
            line.product_template_id = line.product_id.product_tmpl_id

    def _search_product_template_id(self, operator, value):
        return [("product_id.product_tmpl_id", operator, value)]
