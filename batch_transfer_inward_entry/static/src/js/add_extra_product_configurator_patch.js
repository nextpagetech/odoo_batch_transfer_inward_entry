/** @odoo-module **/

import { serializeDateTime } from "@web/core/l10n/dates";
import { patch } from "@web/core/utils/patch";
import { x2ManyCommands } from "@web/core/orm_service";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";
import { getSelectedCustomPtav } from "@sale/js/sale_utils";
import { PurchaseOrderLineProductField } from "@product_variant_attribute_search/js/purchase_product_field";

const baseProductNameGetter =
    Object.getOwnPropertyDescriptor(PurchaseOrderLineProductField.prototype, "productName")?.get ||
    Object.getOwnPropertyDescriptor(
        Object.getPrototypeOf(PurchaseOrderLineProductField.prototype),
        "productName"
    )?.get;

async function applyProduct(record, product) {
    const customAttributesCommands = [x2ManyCommands.set([])];
    for (const ptal of product.attribute_lines || []) {
        const selectedCustomPTAV = getSelectedCustomPtav(ptal);
        if (selectedCustomPTAV) {
            customAttributesCommands.push(
                x2ManyCommands.create(undefined, {
                    custom_product_template_attribute_value_id: [selectedCustomPTAV.id, "unused"],
                    custom_value: ptal.customValue,
                })
            );
        }
    }

    const noVariantPtavIds = (product.attribute_lines || [])
        .filter((ptal) => ptal.create_variant === "no_variant")
        .flatMap((ptal) => ptal.selected_attribute_value_ids);

    const templateId =
        product.product_tmpl_id ||
        record.data.product_template_id?.[0] ||
        record.data.product_template_id?.id;
    const templateDisplay = product.display_name || record.data.product_template_id?.[1];
    await record.update({
        product_id: [product.id, product.display_name],
        product_qty: product.quantity,
        product_no_variant_attribute_value_ids: [x2ManyCommands.set(noVariantPtavIds)],
        product_custom_attribute_value_ids: customAttributesCommands,
        ...(templateId ? { product_template_id: [templateId, templateDisplay] } : {}),
    });
}

const originalOpenConfigurator = PurchaseOrderLineProductField.prototype._openProductConfigurator;
const originalSetup = PurchaseOrderLineProductField.prototype.setup;

patch(PurchaseOrderLineProductField.prototype, {
    setup() {
        originalSetup.call(this);
        const originalUpdateRecord = this.updateRecord;
        this.updateRecord = (value) => {
            const root = this.props.record.model.root;
            if (
                root &&
                root.resModel === "add.extra.move.wizard" &&
                this.props.name === "product_id"
            ) {
                const currentTemplateId = this.props.record.data.product_template_id?.[0];
                const nextId = Array.isArray(value) ? value[0] : value?.[0];
                if (currentTemplateId && nextId && currentTemplateId === nextId && this.relation === "product.template") {
                    // Re-open configurator fresh when selecting the same template again.
                    this._openProductConfigurator(false);
                }
            }
            return originalUpdateRecord.call(this, value);
        };
    },
    get productName() {
        const root = this.props.record.model.root;
        if (
            root &&
            root.resModel === "add.extra.move.wizard" &&
            this.props.name === "product_id"
        ) {
            const productData = this.props.record.data.product_id;
            if (productData && productData[1]) {
                return productData[1].split("\n")[0];
            }
        }
        return baseProductNameGetter ? baseProductNameGetter.call(this) : undefined;
    },
    async _openProductConfigurator(edit = false) {
        const root = this.props.record.model.root;
        if (!root || root.resModel !== "add.extra.move.wizard") {
            return originalOpenConfigurator.call(this, edit);
        }

        const line = this.props.record.data;
        const companyId = root.data.company_id?.[0];
        const currencyId = root.data.currency_id?.[0];
        const orderDate = root.data.date_order;
        const productUOMId = line.product_uom?.[0];

        this.dialog.add(ProductConfiguratorDialog, {
            productTemplateId: line.product_template_id[0],
            ptavIds: [],
            customPtavs: [],
            quantity: line.product_qty || 1,
            productUOMId,
            companyId,
            currencyId,
            soDate: orderDate ? serializeDateTime(orderDate) : undefined,
            edit,
            options: {
                showPrice: false,
                showQuantity: true,
            },
            save: async (mainProduct) => {
                await applyProduct(this.props.record, mainProduct);
            },
            discard: () => {
                this.props.record.update({ product_template_id: false, product_id: false });
            },
        });
    },
});
