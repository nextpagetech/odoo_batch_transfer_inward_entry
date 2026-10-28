{
    "name": "Batch Transfer Inward Entry",
    "summary": "Approve extra products on PO-linked receipts and batch transfers before validation",
    "description": """
Adds an approval workflow for extra products received on purchase-linked receipts,
internal transfers, and batch transfers. Extra products are held for Purchase
Manager review, approved lines can be added to the target purchase order, and
validation is blocked until pending or rejected extra products are resolved.
""",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "author": "Next Page Technologies Pvt Ltd",
    "website": "https://nextpagetechnologies.com",
    "license": "LGPL-3",
    "depends": [
        "stock_picking_batch",
        "purchase_stock",
        "purchase",
        "stock",
        "product_variant_attribute_search",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/views/add_extra_move_wizard_views.xml",
        "wizard/views/batch_detail_operations_wizard_views.xml",
        "views/stock_move_views.xml",
        "views/stock_move_line_views_custom.xml",
        "views/stock_move_line_detail_tree.xml",
        "views/stock_picking_batch_views.xml",
        "views/stock_picking_views.xml",
        "views/stock_picking_views_detail_tab.xml",
        "views/stock_picking_actions_batch_list.xml",
        "views/purchase_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "batch_transfer_inward_entry/static/src/js/add_extra_product_configurator_patch.js",
            "batch_transfer_inward_entry/static/src/js/batch_detail_sml_x2_many.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
