# Product Variant Attribute Search

This module adds dynamic attribute-based filtering in several product selection
and reporting areas, plus a Purchase configurator flow.

## Features
- Product Variants search panel with dynamic Attributes and value dropdowns (type to search, multi-select).
- Category is kept in the Search Panel to keep it visible and useful.
- Stock Report (Inventory -> Reporting -> Stock) search panel includes Attributes.
- Stock Quants search panel includes Attributes (when opening the Locations/quants view).
- Purchase Order Line "Search More" adds an Attributes filter drawer.
- Purchase "Search More" includes a Product Template dropdown to scope attributes and results.
- Purchase Order Line uses Product Configurator dialog (Sales-like behavior).
- Purchase configurator attribute lines use searchable multi-select dropdowns.
- Configurator uses attribute filters (OR within attribute, AND across attributes) to pick a matching variant.
- Configurator attribute selectors are displayed in a responsive grid (up to 5 columns).
- Manufacturing Order "Product to build" excludes purchase_ok and service products.
- Action overrides ensure Purchase/Inventory Product Variants menus use the correct search view.

## How the Attributes filter works
- Within the same attribute: selecting multiple values is OR.
- Across different attributes: selection is AND.
- Attributes/values are dynamic; new values appear automatically.

## Installation
1) Copy module to `custom_addons/product_variant_attribute_search`
2) Update apps list
3) Upgrade module `product_variant_attribute_search`
4) Hard refresh the browser (Ctrl+F5)

## Usage
- Sales/Purchase/Inventory/Manufacturing -> Products -> Product Variants
  - Use the left Attribute dropdowns to filter variants (multi-select values).
- Inventory -> Reporting -> Stock
  - Use Attributes in the left Search Panel to filter product variants.
- Purchase Order -> Add a product -> Search More
  - Use the Attributes button to open the attribute filter drawer.
- Manufacturing -> New MO -> Product
  - Only products with `purchase_ok = False` and `type != service` are shown.

## Notes
- The Product Variants search panel is defined on `product.product` search views.
- The MO product domain override is view-based and can be adjusted if needed.
- The purchase configurator depends on `sale` for the Product Configurator dialog.

## Troubleshooting
- If Attributes do not appear, upgrade the module and hard refresh.
- Ensure the user is in the Product Variant group (`product.group_product_variant`).
- If a menu uses a custom action/search view, it may need an explicit override.
