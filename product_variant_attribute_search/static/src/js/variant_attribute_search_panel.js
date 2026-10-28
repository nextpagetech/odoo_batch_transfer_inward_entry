/** @odoo-module */

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { SearchPanel } from "@web/search/search_panel/search_panel";

class VariantAttributeSearchPanel extends Component {
    static template = "product_variant_attribute_search.VariantAttributeSearchPanel";
    static components = { SelectMenu };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: false,
            attributes: [],
            selections: {},
            valuesByAttribute: {},
        });
        this.labels = {
            title: _t("Attributes"),
            clear: _t("Clear"),
            apply: _t("Apply"),
            empty: _t("No attributes found."),
            loading: _t("Loading attributes..."),
            valuesPlaceholder: _t("Type to search values"),
            valuesLoading: _t("Loading values..."),
        };
        this.groupId = null;

        onWillStart(async () => {
            if (this.shouldShow) {
                await this.loadAttributes();
                await this.loadDefaultValues();
            }
        });
    }

    get shouldShow() {
        const resModel = this.env.searchModel?.resModel;
        const fields = this.env.searchModel?.searchViewFields || {};
        const hasAttributeField = Object.prototype.hasOwnProperty.call(
            fields,
            "product_template_attribute_value_ids"
        );
        return ["product.product", "stock.quant"].includes(resModel) || hasAttributeField;
    }

    get hasSelection() {
        return Object.values(this.state.selections).some((valueIds) => valueIds?.length);
    }

    async loadAttributes() {
        this.state.loading = true;
        const attributes = await this.orm.call(
            "product.product",
            "get_variant_attribute_filters",
            [],
            { context: this.env.searchModel?.context || {} }
        );
        this.state.attributes = attributes || [];
        this.state.loading = false;
    }

    async loadDefaultValues() {
        const attributes = this.state.attributes || [];
        if (!attributes.length) {
            return;
        }
        for (const attr of attributes) {
            if (this.state.valuesByAttribute[attr.id]?.values?.length) {
                continue;
            }
            await this._fetchValues(attr.id, "", 5);
        }
    }

    async _fetchValues(attributeId, search, limit) {
        const prev = this.state.valuesByAttribute[attributeId] || {
            values: [],
            loading: false,
            search: "",
        };
        this.state.valuesByAttribute = {
            ...this.state.valuesByAttribute,
            [attributeId]: { ...prev, loading: true, search },
        };
        const values = await this.orm.call(
            "product.product",
            "get_variant_attribute_values",
            [attributeId, search, limit],
            { context: this.env.searchModel?.context || {} }
        );
        const merged = new Map();
        for (const value of prev.values || []) {
            merged.set(value.id, value);
        }
        for (const value of values || []) {
            merged.set(value.id, value);
        }
        this.state.valuesByAttribute = {
            ...this.state.valuesByAttribute,
            [attributeId]: {
                loading: false,
                search,
                values: Array.from(merged.values()),
            },
        };
    }

    getSelectedValueIds(attributeId) {
        return this.state.selections[attributeId] || [];
    }

    isValuesLoading(attributeId) {
        return Boolean(this.state.valuesByAttribute[attributeId]?.loading);
    }

    getValueChoices(attributeId) {
        const values = this.state.valuesByAttribute[attributeId]?.values || [];
        return values.map((value) => ({
            value: value.id,
            label: value.name,
        }));
    }

    getValuePlaceholder(attributeId) {
        return this.isValuesLoading(attributeId)
            ? this.labels.valuesLoading
            : this.labels.valuesPlaceholder;
    }

    async onValueSearch(attributeId, searchString) {
        const search = (searchString || "").trim();
        if (!search) {
            await this._fetchValues(attributeId, "", 5);
            return;
        }
        await this._fetchValues(attributeId, search, 50);
    }

    onValuesSelected(attributeId, valueIds) {
        this.state.selections = {
            ...this.state.selections,
            [attributeId]: valueIds || [],
        };
    }

    clearAll() {
        this.state.selections = {};
        if (this.groupId) {
            this.env.searchModel.deactivateGroup(this.groupId);
            this.groupId = null;
        }
    }

    async applyDomain() {
        const domain = [];
        for (const [, valueIds] of Object.entries(this.state.selections)) {
            if (valueIds?.length) {
                domain.push([
                    "product_template_attribute_value_ids.product_attribute_value_id",
                    "in",
                    valueIds,
                ]);
            }
        }

        if (!domain.length) {
            if (this.groupId) {
                this.env.searchModel.deactivateGroup(this.groupId);
                this.groupId = null;
            }
            return;
        }

        const searchModel = this.env.searchModel;
        if (this.groupId) {
            searchModel.deactivateGroup(this.groupId);
            this.groupId = null;
        }

        const description = this.labels.title;
        const preFilter = {
            description,
            domain,
            invisible: "True",
            type: "filter",
        };
        const nextGroupId = searchModel.nextGroupId;
        searchModel.createNewFilters([preFilter]);
        this.groupId = nextGroupId;
    }
}

patch(SearchPanel, {
    components: { ...SearchPanel.components, VariantAttributeSearchPanel },
});

patch(SearchPanel.prototype, {
    get hasVariantAttributePanel() {
        const resModel = this.env.searchModel?.resModel;
        const fields = this.env.searchModel?.searchViewFields || {};
        const hasAttributeField = Object.prototype.hasOwnProperty.call(
            fields,
            "product_template_attribute_value_ids"
        );
        return ["product.product", "stock.quant"].includes(resModel) || hasAttributeField;
    },
});
