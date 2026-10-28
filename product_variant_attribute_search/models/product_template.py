from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model
    def _purchase_attribute_company_domain(self):
        companies = self.env.companies
        if companies:
            return [
                "|",
                ("company_id", "=", False),
                ("company_id", "in", companies.ids),
            ]
        return []

    @api.model
    def _purchase_template_domain(self):
        domain = [("purchase_ok", "=", True)]
        company_domain = self._purchase_attribute_company_domain()
        if company_domain:
            domain += company_domain
        return domain

    @api.model
    def get_purchase_templates(self):
        templates = self.search(self._purchase_template_domain()).sorted("name")
        return templates.read(["name"])

    @api.model
    def get_purchase_template_attributes(self, template_id):
        template = self.search(self._purchase_template_domain() + [("id", "=", template_id)], limit=1)
        if not template:
            return []
        attributes = template.attribute_line_ids.mapped("attribute_id").sorted("name")
        return attributes.read(["name"])

    @api.model
    def get_purchase_template_attribute_values(self, template_id, attribute_id, search=None, limit=None):
        template = self.search(self._purchase_template_domain() + [("id", "=", template_id)], limit=1)
        if not template:
            return []
        lines = template.attribute_line_ids.filtered(lambda line: line.attribute_id.id == attribute_id)
        values = lines.mapped("value_ids")
        if search:
            values = values.filtered(lambda val: search.lower() in (val.name or "").lower())
        values = values.sorted("name")
        if limit:
            values = values[: int(limit)]
        return values.read(["name"])

    # Computed helper so the search panel can list all attribute values on templates.
    product_template_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        string="Attribute Values",
        compute="_compute_template_attribute_values",
        compute_sudo=True,
        store=True,
    )

    @api.depends(
        "attribute_line_ids.product_template_value_ids",
        "product_variant_ids.product_template_attribute_value_ids",
    )
    def _compute_template_attribute_values(self):
        for template in self:
            # Collect attribute values from template lines (ptav) and from existing variants (ptav)
            line_values = template.attribute_line_ids.mapped("product_template_value_ids")
            variant_values = template.product_variant_ids.mapped("product_template_attribute_value_ids")
            template.product_template_attribute_value_ids = line_values | variant_values

    @api.model
    def pvatt_get_variant_for_filters(self, product_template_id, attribute_filters=None, current_product_id=None):
        """Return a matching variant for the given template + attribute filter groups.

        attribute_filters = [
            {"attribute_id": int, "ptav_ids": [int, ...]},
            ...
        ]
        """
        template = self.browse(product_template_id).exists()
        if not template:
            return {"product_id": False, "ptav_ids": []}

        domain = [("product_tmpl_id", "=", template.id)]
        for line in attribute_filters or []:
            ptav_ids = [int(pid) for pid in (line.get("ptav_ids") or [])]
            if not ptav_ids:
                continue
            ptav_ids = self.env["product.template.attribute.value"].browse(ptav_ids).filtered(
                lambda ptav: ptav.product_tmpl_id.id == template.id
            ).ids
            if ptav_ids:
                domain.append(("product_template_attribute_value_ids", "in", ptav_ids))

        variants = self.env["product.product"].search(domain)
        variant = False
        if current_product_id and current_product_id in variants.ids:
            variant = self.env["product.product"].browse(current_product_id)
        else:
            variant = variants[:1]

        return {
            "product_id": variant.id or False,
            "ptav_ids": variant.product_template_attribute_value_ids.ids if variant else [],
        }
