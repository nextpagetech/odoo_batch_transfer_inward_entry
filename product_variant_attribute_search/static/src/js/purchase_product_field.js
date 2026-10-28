/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { serializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { x2ManyCommands } from "@web/core/orm_service";
import {
    ProductLabelSectionAndNoteField,
    productLabelSectionAndNoteField,
} from "@account/components/product_label_section_and_note_field/product_label_section_and_note_field";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";
import { getSelectedCustomPtav } from "@sale/js/sale_utils";

async function applyProduct(record, product) {
    const customAttributesCommands = [
        x2ManyCommands.set([]),
    ];
    for (const ptal of product.attribute_lines) {
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

    const noVariantPtavIds = product.attribute_lines
        .filter((ptal) => ptal.create_variant === "no_variant")
        .flatMap((ptal) => ptal.selected_attribute_value_ids);

    await record._update({
        product_id: [product.id, product.display_name],
        product_qty: product.quantity,
        product_no_variant_attribute_value_ids: [x2ManyCommands.set(noVariantPtavIds)],
        product_custom_attribute_value_ids: customAttributesCommands,
    });
}

export class PurchaseOrderLineProductField extends ProductLabelSectionAndNoteField {
    static props = {
        ...ProductLabelSectionAndNoteField.props,
    };

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        let isMounted = false;
        let isInternalUpdate = false;
        const { updateRecord } = this;
        this.updateRecord = (value) => {
            isInternalUpdate = true;
            return updateRecord.call(this, value);
        };
        useEffect(
            (value) => {
                if (!isMounted) {
                    isMounted = true;
                } else if (value && isInternalUpdate) {
                    if (this.relation === "product.template") {
                        this._onProductTemplateUpdate();
                    }
                }
                isInternalUpdate = false;
            },
            () => [Array.isArray(this.value) && this.value[0]]
        );
    }

    async _onProductTemplateUpdate() {
        const templateId = this.props.record.data.product_template_id?.[0];
        if (!templateId) {
            return;
        }
        const result = await this.orm.call(
            "product.template",
            "get_single_product_variant",
            [templateId],
            { context: this.context }
        );
        if (result && result.product_id) {
            await this.props.record.update({
                product_id: [result.product_id, result.product_name],
            });
        } else {
            this._openProductConfigurator();
        }
    }

    async _openProductConfigurator(edit = false) {
        const orderRecord = this.props.record.model.root;
        const line = this.props.record.data;
        const companyId = orderRecord.data.company_id?.[0];
        const currencyId = orderRecord.data.currency_id?.[0];
        const orderDate = orderRecord.data.date_order;
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
                orderRecord.data.order_line.leaveEditMode();
            },
            discard: () => {
                orderRecord.data.order_line.delete(this.props.record);
            },
        });
    }
}

export const purchaseOrderLineProductField = {
    ...productLabelSectionAndNoteField,
    component: PurchaseOrderLineProductField,
};

registry.category("fields").add("pol_product_many2one", purchaseOrderLineProductField);
