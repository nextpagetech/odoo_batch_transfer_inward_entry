from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _variant_attribute_company_domain(self):
        companies = self.env.companies
        if companies:
            return [
                "|",
                ("product_tmpl_id.company_id", "=", False),
                ("product_tmpl_id.company_id", "in", companies.ids),
            ]
        return []

    @api.model
    def _variant_template_attribute_domain(self):
        domain = self._variant_attribute_company_domain()
        return domain

    @api.model
    def _purchase_attribute_company_domain(self):
        companies = self.env.companies
        if companies:
            return [
                "|",
                ("product_tmpl_id.company_id", "=", False),
                ("product_tmpl_id.company_id", "in", companies.ids),
            ]
        return []

    @api.model
    def _purchase_template_attribute_domain(self):
        domain = [
            ("product_tmpl_id.purchase_ok", "=", True),
        ]
        company_domain = self._purchase_attribute_company_domain()
        if company_domain:
            domain += company_domain
        return domain

    @api.model
    def get_purchase_attribute_filters(self):
        line_domain = self._purchase_template_attribute_domain()
        groups = self.env["product.template.attribute.line"].read_group(
            line_domain,
            ["attribute_id"],
            ["attribute_id"],
        )
        attribute_ids = [
            group["attribute_id"][0] for group in groups if group.get("attribute_id")
        ]
        attributes = self.env["product.attribute"].browse(attribute_ids)
        attributes = attributes.sorted("name")
        return attributes.read(["name"])

    @api.model
    def get_purchase_attribute_values(self, attribute_id, search=None, limit=None):
        line_domain = self._purchase_template_attribute_domain()
        line_domain.append(("attribute_id", "=", attribute_id))
        if search:
            line_domain.append(("value_ids.name", "ilike", search))
        groups = self.env["product.template.attribute.line"].read_group(
            line_domain,
            ["value_ids"],
            ["value_ids"],
        )
        value_ids = [group["value_ids"][0] for group in groups if group.get("value_ids")]
        values = self.env["product.attribute.value"].browse(value_ids).sorted("name")
        if limit:
            values = values[: int(limit)]
        return values.read(["name"])

    @api.model
    def get_purchase_attribute_domain(self, attribute_filters):
        domain = []
        for line in attribute_filters or []:
            value_ids = line.get("value_ids") or []
            if value_ids:
                domain.append(
                    (
                        "product_template_attribute_value_ids.product_attribute_value_id",
                        "in",
                        value_ids,
                    )
                )
        return domain

    @api.model
    def get_variant_attribute_filters(self):
        line_domain = self._variant_template_attribute_domain()
        groups = self.env["product.template.attribute.line"].read_group(
            line_domain,
            ["attribute_id"],
            ["attribute_id"],
        )
        attribute_ids = [
            group["attribute_id"][0] for group in groups if group.get("attribute_id")
        ]
        attributes = self.env["product.attribute"].browse(attribute_ids).sorted("name")
        return attributes.read(["name"])

    @api.model
    def get_variant_attribute_values(self, attribute_id, search=None, limit=None):
        line_domain = self._variant_template_attribute_domain()
        line_domain.append(("attribute_id", "=", attribute_id))
        if search:
            line_domain.append(("value_ids.name", "ilike", search))
        groups = self.env["product.template.attribute.line"].read_group(
            line_domain,
            ["value_ids"],
            ["value_ids"],
        )
        value_ids = [group["value_ids"][0] for group in groups if group.get("value_ids")]
        values = self.env["product.attribute.value"].browse(value_ids).sorted("name")
        if limit:
            values = values[: int(limit)]
        return values.read(["name"])
