/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import { patch } from "@web/core/utils/patch";
import { ProductTemplateAttributeLine } from "@sale/js/product_template_attribute_line/product_template_attribute_line";

patch(ProductTemplateAttributeLine, {
    components: { ...ProductTemplateAttributeLine.components, SelectMenu },
});

patch(ProductTemplateAttributeLine.prototype, {
    get pvattChoices() {
        return (this.props.attribute_values || []).map((ptav) => ({
            value: ptav.id,
            label: this.getPTAVSelectName(ptav),
        }));
    },

    get pvattSelectedIds() {
        return this.props.selected_attribute_value_ids || [];
    },

    get pvattPlaceholder() {
        return _t("Type to search values");
    },

    async pvattOnSelect(valueIds) {
        if (!this || !this.props) {
            return;
        }
        const nextIds = Array.isArray(valueIds) ? valueIds : [];
        const prev = new Set(this.props.selected_attribute_value_ids || []);
        const next = new Set(nextIds);

        for (const id of prev) {
            if (!next.has(id)) {
                await this.env.updateProductTemplateSelectedPTAV(
                    this.props.productTmplId,
                    this.props.id,
                    id,
                    true
                );
            }
        }

        for (const id of next) {
            if (!prev.has(id)) {
                await this.env.updateProductTemplateSelectedPTAV(
                    this.props.productTmplId,
                    this.props.id,
                    id,
                    true
                );
            }
        }
    },
});
