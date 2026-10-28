from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AddExtraMoveWizard(models.TransientModel):
    _name = "add.extra.move.wizard"
    _description = "Add Extra Product to Batch"

    batch_id = fields.Many2one("stock.picking.batch")
    picking_id = fields.Many2one(
        "stock.picking",
        required=True,
        domain="[('id', 'in', batch_picking_ids)]",
        help="Which receipt to attach the new line to.",
    )
    batch_picking_ids = fields.Many2many(
        "stock.picking",
        compute="_compute_batch_pickings",
        string="Batch Receipts",
    )
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        domain=[("purchase_ok", "=", True)],
    )
    product_template_has_multiple_variants = fields.Boolean(
        compute="_compute_product_template_variants",
        string="Has Multiple Variants",
    )
    product_id = fields.Many2one(
        "product.product",
        domain=[("purchase_ok", "=", True)],
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        "product.template.attribute.value",
        string="No Variant Attributes",
    )
    product_custom_attribute_value_ids = fields.Many2many(
        "product.attribute.custom.value",
        "add_extra_move_wizard_custom_value_rel",
        "wizard_id",
        "custom_value_id",
        string="Custom Attributes",
    )
    product_uom = fields.Many2one(
        "uom.uom",
        compute="_compute_product_uom",
        readonly=True,
    )
    product_qty = fields.Float(required=True)
    company_id = fields.Many2one(
        "res.company",
        compute="_compute_configurator_context",
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_configurator_context",
        readonly=True,
    )
    date_order = fields.Datetime(
        compute="_compute_configurator_context",
        readonly=True,
    )
    target_purchase_order_id = fields.Many2one(
        "purchase.order",
        domain="[('id', 'in', available_po_ids)]",
        help="PO that will receive the extra product (can be changed before approval).",
    )
    available_po_ids = fields.Many2many(
        "purchase.order",
        compute="_compute_available_pos",
        string="Available POs",
    )
    note = fields.Char()

    # -------------------------------------------------------------------------
    # Compute helpers
    # -------------------------------------------------------------------------
    @api.depends("batch_id", "batch_id.picking_ids", "picking_id", "target_purchase_order_id")
    def _compute_batch_pickings(self):
        Picking = self.env["stock.picking"]
        for wizard in self:
            if wizard.batch_id:
                cands = wizard.batch_id.picking_ids
                if wizard.target_purchase_order_id:
                    # include internal pickings linked through move relations as well
                    po = wizard.target_purchase_order_id
                    def _match(p):
                        if p.purchase_id == po:
                            return True
                        moves = p.move_ids
                        if moves.filtered(lambda m: m.purchase_line_id and m.purchase_line_id.order_id == po):
                            return True
                        if moves.filtered(lambda m: po in m.move_orig_ids.mapped("purchase_line_id.order_id")):
                            return True
                        if moves.filtered(lambda m: po in m.move_dest_ids.mapped("purchase_line_id.order_id")):
                            return True
                        extra_po_ids = getattr(p, "extra_purchase_order_ids", False)
                        return bool(extra_po_ids and po in extra_po_ids)
                    cands = cands.filtered(_match)
                wizard.batch_picking_ids = cands
                # auto-select if only one candidate is possible
                if (not wizard.picking_id or wizard.picking_id not in cands) and len(cands) == 1:
                    wizard.picking_id = cands[0]
                continue
            picking = wizard.picking_id
            if not picking:
                default_picking_id = wizard.env.context.get("default_picking_id")
                picking = Picking.browse(default_picking_id) if default_picking_id else Picking.browse()
            cands = picking and Picking.browse([picking.id]) or Picking.browse()
            if wizard.target_purchase_order_id:
                cands = cands.filtered(lambda p: p.purchase_id == wizard.target_purchase_order_id)
            wizard.batch_picking_ids = cands
            if (not wizard.picking_id or wizard.picking_id not in cands) and len(cands) == 1:
                wizard.picking_id = cands[0]

    @api.depends(
        "batch_id",
        "batch_id.picking_ids",
        "batch_id.purchase_order_ids",
        "picking_id",
        "picking_id.purchase_id",
    )
    def _compute_available_pos(self):
        PurchaseOrder = self.env["purchase.order"]
        # Include RFQs too so the wizard lists all POs attached to the batch
        valid_states = ("draft", "sent", "to approve", "purchase", "done")
        for wizard in self:
            orders = PurchaseOrder.browse()
            if wizard.batch_id:
                batch_orders = wizard.batch_id.purchase_order_ids
                # Always enrich from pickings' move chains to cover storage batches
                pickings = wizard.batch_id.picking_ids
                orders |= pickings.mapped("move_ids.purchase_line_id.order_id")
                orders |= pickings.mapped("move_ids.move_orig_ids.purchase_line_id.order_id")
                orders |= pickings.mapped("move_ids.move_dest_ids.purchase_line_id.order_id")
                # include any direct purchase_id on pickings (rare on internal)
                orders |= wizard.batch_id.picking_ids.mapped("purchase_id")
                orders |= batch_orders
            if wizard.picking_id and wizard.picking_id.purchase_id:
                orders |= wizard.picking_id.purchase_id
            extra_po_ids = wizard.env.context.get("extra_related_purchase_order_ids")
            if extra_po_ids:
                orders |= PurchaseOrder.browse(extra_po_ids)
            if not wizard.batch_id and not wizard.picking_id:
                default_picking_id = wizard.env.context.get("default_picking_id")
                if default_picking_id:
                    picking = wizard.env["stock.picking"].browse(default_picking_id)
                    if picking and picking.purchase_id:
                        orders |= picking.purchase_id
            orders = orders.filtered(lambda po: po and po.state in valid_states)

            if wizard.target_purchase_order_id and wizard.target_purchase_order_id not in orders:
                wizard.target_purchase_order_id = False
            if not wizard.target_purchase_order_id and len(orders) == 1:
                wizard.target_purchase_order_id = orders[:1]

            wizard.available_po_ids = orders

    # -------------------------------------------------------------------------
    # Onchange / defaults
    # -------------------------------------------------------------------------
    @api.onchange("product_id")
    def _onchange_product_id(self):
        for wizard in self:
            wizard.product_template_id = wizard.product_id.product_tmpl_id if wizard.product_id else False

    @api.onchange("product_template_id")
    def _onchange_product_template_id(self):
        for wizard in self:
            template = wizard.product_template_id
            if not template:
                wizard.product_id = False
                return
            if template.product_variant_count == 1:
                wizard.product_id = template.product_variant_id or template.product_variant_ids[:1]
            elif wizard.product_id and wizard.product_id.product_tmpl_id != template:
                wizard.product_id = False

    @api.onchange("target_purchase_order_id", "product_qty", "product_uom")
    def _onchange_target_purchase_order(self):
        for wizard in self:
            wizard._auto_select_picking_from_target_po()
            # also explicitly restrict the domain of picking to related pickings of selected PO
            cands = wizard.batch_picking_ids
            if wizard.batch_id and wizard.target_purchase_order_id:
                po = wizard.target_purchase_order_id
                def _match(p):
                    if p.purchase_id == po:
                        return True
                    moves = p.move_ids
                    if moves.filtered(lambda m: m.purchase_line_id and m.purchase_line_id.order_id == po):
                        return True
                    if moves.filtered(lambda m: po in m.move_orig_ids.mapped("purchase_line_id.order_id")):
                        return True
                    if moves.filtered(lambda m: po in m.move_dest_ids.mapped("purchase_line_id.order_id")):
                        return True
                    extra_po_ids = getattr(p, "extra_purchase_order_ids", False)
                    return bool(extra_po_ids and po in extra_po_ids)
                cands = wizard.batch_id.picking_ids.filtered(_match)
            return {"domain": {"picking_id": [("id", "in", cands.ids)]}}

    def _auto_select_picking_from_target_po(self):
        for wizard in self:
            target_po = wizard.target_purchase_order_id
            if not target_po:
                continue
            candidate_pickings = wizard.batch_picking_ids
            if not candidate_pickings and wizard.batch_id:
                candidate_pickings = wizard.batch_id.picking_ids
            if not candidate_pickings and wizard.picking_id:
                candidate_pickings = wizard.picking_id

            def _picking_match(picking):
                if picking.purchase_id == target_po:
                    return True
                moves = picking.move_ids
                if moves.filtered(lambda m: target_po in m.purchase_line_id.mapped("order_id")):
                    return True
                if moves.filtered(
                    lambda m: target_po in m.move_orig_ids.mapped("purchase_line_id.order_id")
                ):
                    return True
                if moves.filtered(
                    lambda m: target_po in m.move_dest_ids.mapped("purchase_line_id.order_id")
                ):
                    return True
                extra_po_ids = getattr(picking, "extra_purchase_order_ids", False)
                return bool(extra_po_ids and target_po in extra_po_ids)

            related_pickings = candidate_pickings.filtered(_picking_match)
            if not related_pickings and wizard.picking_id and _picking_match(wizard.picking_id):
                related_pickings = wizard.picking_id
            if not related_pickings:
                continue

            ordered = related_pickings.sorted(
                key=lambda picking: (
                    picking.scheduled_date or picking.date or picking.create_date,
                    picking.id,
                )
            )
            selected = ordered[:1]
            if selected and wizard.picking_id != selected:
                wizard.picking_id = selected

    @api.depends("target_purchase_order_id", "picking_id", "batch_id")
    def _compute_configurator_context(self):
        for wizard in self:
            purchase = wizard.target_purchase_order_id
            if not purchase and wizard.picking_id and wizard.picking_id.purchase_id:
                purchase = wizard.picking_id.purchase_id
            company = (
                purchase.company_id
                if purchase
                else (wizard.picking_id.company_id if wizard.picking_id else wizard.env.company)
            )
            currency = purchase.currency_id if purchase else company.currency_id
            date_order = (
                purchase.date_order
                if purchase
                else (
                    wizard.picking_id.scheduled_date
                    if wizard.picking_id and wizard.picking_id.scheduled_date
                    else (
                        wizard.picking_id.date
                        if wizard.picking_id and wizard.picking_id.date
                        else fields.Datetime.now()
                    )
                )
            )
            wizard.company_id = company
            wizard.currency_id = currency
            wizard.date_order = date_order

    # -------------------------------------------------------------------------
    # Main action
    # -------------------------------------------------------------------------
    def action_add(self):
        self.ensure_one()
        picking = self.picking_id
        if picking.picking_type_id.code not in {"incoming", "internal"}:
            raise UserError(_("Extra products can only be added on receipts or quality control transfers."))
        if not self.product_id:
            raise UserError(_("Select a product variant."))
        product_uom = self.product_uom or self.product_id.uom_po_id or self.product_id.uom_id
        if not product_uom:
            raise UserError(_("Select a UoM."))
        if self.product_qty <= 0:
            raise UserError(_("Quantity must be greater than zero."))
        if not (self.target_purchase_order_id or self.available_po_ids):
            raise UserError(_("Select the purchase order that must receive the extra product."))

        move_vals = {
            "name": self.product_id.display_name,
            "product_id": self.product_id.id,
            "product_uom": product_uom.id,
            "product_uom_qty": self.product_qty,
            "picking_id": picking.id,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
            "company_id": picking.company_id.id,
            "partner_id": picking.partner_id.id if picking.partner_id else False,
        }

        move = self.env["stock.move"].with_context(batch_form_add_extra=True).create(move_vals)

        # Provide an editable move line so lots/serials can be set in the Detailed Operations tab.
        # Keep done qty at 0; demand stays on the move (product_uom_qty).
        move_line_vals = move._prepare_move_line_vals()
        move_line_vals.update({"lot_id": False, "lot_name": False})

        self.env["stock.move.line"].create(move_line_vals)

        if self.target_purchase_order_id:
            move.target_purchase_order_id = self.target_purchase_order_id

        if self.note:
            message = _(
                "Extra product proposed: %s (%s %s). %s",
                self.product_id.display_name,
                self.product_qty,
                product_uom.name,
                self.note,
            )
            picking.message_post(body=message)
            if picking.batch_id:
                batch_msg = _(
                    "Extra product proposed on %s: %s (%s %s). %s",
                    picking.name,
                    self.product_id.display_name,
                    self.product_qty,
                    product_uom.name,
                    self.note,
                )
                picking.batch_id.message_post(body=batch_msg)

        return {"type": "ir.actions.act_window_close"}

    @api.depends("product_template_id")
    def _compute_product_template_variants(self):
        for wizard in self:
            wizard.product_template_has_multiple_variants = bool(
                wizard.product_template_id
                and wizard.product_template_id.product_variant_count > 1
            )

    @api.depends("product_id")
    def _compute_product_uom(self):
        for wizard in self:
            if wizard.product_id:
                wizard.product_uom = wizard.product_id.uom_po_id or wizard.product_id.uom_id
            else:
                wizard.product_uom = False
