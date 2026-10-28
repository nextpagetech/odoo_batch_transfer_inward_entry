/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";

const _superSetup = ProductConfiguratorDialog.prototype.setup;
const _superGetCombination = ProductConfiguratorDialog.prototype._getCombination;
const _superIsPossibleCombination = ProductConfiguratorDialog.prototype._isPossibleCombination;

patch(ProductConfiguratorDialog.prototype, {
    setup() {
        _superSetup.call(this);
        this.orm = useService("orm");
    },

    _pvattGetFilterGroups(product) {
        const groups = [];
        for (const line of product.attribute_lines || []) {
            if (line.create_variant === "no_variant") {
                continue;
            }
            const valueIds = line.selected_attribute_value_ids || [];
            if (valueIds.length) {
                groups.push({
                    attribute_id: line.attribute.id,
                    ptav_ids: valueIds,
                });
            }
        }
        return groups;
    },

    _pvattGetExtraPtavIds(product) {
        const extra = [];
        for (const line of product.attribute_lines || []) {
            if (line.create_variant === "no_variant") {
                extra.push(...(line.selected_attribute_value_ids || []));
            }
        }
        return extra;
    },

    async _pvattRefreshVariantForFilters(product) {
        if (!this.orm) {
            return;
        }

        const filters = this._pvattGetFilterGroups(product);
        const result = await this.orm.call(
            "product.template",
            "pvatt_get_variant_for_filters",
            [product.product_tmpl_id],
            {
                attribute_filters: filters,
                current_product_id: product.id || false,
            }
        );

        if (result && result.product_id) {
            const extraIds = this._pvattGetExtraPtavIds(product);
            product._pvatt_combination_ids = [
                ...new Set([...(result.ptav_ids || []), ...extraIds]),
            ];
            product._pvatt_no_match = false;
        } else {
            product._pvatt_combination_ids = null;
            product._pvatt_no_match = true;
        }

        this._checkExclusions(product);

        if (!product._pvatt_no_match && this._isPossibleCombination(product)) {
            const updatedValues = await this._updateCombination(product, product.quantity);
            Object.assign(product, updatedValues);
            if (
                !product.id &&
                product.attribute_lines.every((ptal) => ptal.create_variant === "always")
            ) {
                const combination = this._getCombination(product);
                product.archived_combinations = product.archived_combinations.concat([combination]);
                this._checkExclusions(product);
            }
        }
    },

    async _updateProductTemplateSelectedPTAV(productTmplId, ptalId, ptavId, isMulti) {
        const product = this._findProduct(productTmplId);
        if (!product) {
            return;
        }
        const ptal = product.attribute_lines.find((line) => line.id === ptalId);
        if (!ptal) {
            return;
        }
        ptavId = parseInt(ptavId);
        if (isMulti) {
            const selectedPtavIds = new Set(ptal.selected_attribute_value_ids);
            selectedPtavIds.has(ptavId)
                ? selectedPtavIds.delete(ptavId)
                : selectedPtavIds.add(ptavId);
            ptal.selected_attribute_value_ids = Array.from(selectedPtavIds);
        } else {
            ptal.selected_attribute_value_ids = [ptavId];
        }

        await this._pvattRefreshVariantForFilters(product);
    },

    _getCombination(product) {
        if (product && product._pvatt_combination_ids && product._pvatt_combination_ids.length) {
            return product._pvatt_combination_ids;
        }
        return _superGetCombination.call(this, product);
    },

    _isPossibleCombination(product) {
        if (product && product._pvatt_no_match) {
            return false;
        }
        if (product && product._pvatt_combination_ids && product._pvatt_combination_ids.length) {
            const selectedPtavIds = new Set(product._pvatt_combination_ids);
            return product.attribute_lines.every((ptal) => {
                return ptal.attribute_values
                    .filter((ptav) => selectedPtavIds.has(ptav.id))
                    .every((ptav) => !ptav.excluded);
            });
        }
        return _superIsPossibleCombination.call(this, product);
    },
});
