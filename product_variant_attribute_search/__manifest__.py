{
    "name": "Product Variant Attribute Search",
    "version": "18.0.1.0.0",
    "category": "Inventory/Product",
    "license": "LGPL-3",
    "summary": "Filter product variants by attributes across Purchase and Inventory",
    "description": """
Add dynamic, searchable attribute filters to product variant selection in Odoo.
Filter variants in product and stock views, narrow Purchase Order product searches,
and select matching variants through an enhanced Purchase product configurator.
""",
    "author": "Next Page Technologies Pvt Ltd",
    "website": "https://nextpagetechnologies.com",
    "support": "hello@nextpagetechnologies.com",
    "depends": ["product", "stock", "purchase", "sale", "web", "mrp"],
    "data": [
        "views/purchase_order_line_attribute_filter.xml",
        "views/purchase_order_line_product_configurator.xml",
        "views/product_variant_attribute_searchpanel.xml",
        "views/product_stock_report_attribute_searchpanel.xml",
        "views/product_variant_action_search_view_override.xml",
        "views/mrp_production_product_domain.xml",
        "views/stock_quant_attribute_searchpanel.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "product_variant_attribute_search/static/src/js/attribute_filter_dialog.js",
            "product_variant_attribute_search/static/src/js/purchase_product_field.js",
            "product_variant_attribute_search/static/src/js/variant_attribute_search_panel.js",
            "product_variant_attribute_search/static/src/js/product_configurator_attribute_select.js",
            "product_variant_attribute_search/static/src/js/product_configurator_attribute_filter.js",
            "product_variant_attribute_search/static/src/xml/attribute_filter_dialog.xml",
            "product_variant_attribute_search/static/src/xml/variant_attribute_search_panel.xml",
            "product_variant_attribute_search/static/src/xml/product_configurator_attribute_select.xml",
            "product_variant_attribute_search/static/src/xml/product_configurator_attribute_grid.xml",
            "product_variant_attribute_search/static/src/scss/attribute_filter_dialog.scss",
            "product_variant_attribute_search/static/src/scss/variant_attribute_search_panel.scss",
            "product_variant_attribute_search/static/src/scss/product_configurator_attribute_select.scss",
            "product_variant_attribute_search/static/src/scss/product_configurator_attribute_grid.scss",
        ],
    },
    "images": [
        "static/description/banner.png",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
