/** Purchase Order Line "Search More" attribute filter panel. */
/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

patch(SelectCreateDialog, {
    components: { ...SelectCreateDialog.components, SelectMenu },
});

patch(SelectCreateDialog.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.attrState = useState({
            open: false,
            loadingTemplates: false,
            loadingAttributes: false,
            attributes: [],
            templates: [],
            templateId: null,
            selections: {},
            valuesByAttribute: {},
            appliedRows: [],
            domain: [],
        });
        this.attributeFilterLabels = {
            title: _t("Attributes"),
            noFilters: _t("No attribute filters"),
            loading: _t("Loading attributes..."),
            templatePlaceholder: _t("Product Template"),
            templateAll: _t("All Templates"),
            valuesPlaceholder: _t("Type to search values"),
            clear: _t("Clear"),
            apply: _t("Apply"),
            emptyAttributes: _t("No purchasable attributes found."),
        };

        onWillStart(async () => {
            if (this.shouldShowAttributeFilter) {
                await this.loadTemplates();
                await this.loadAttributes();
                await this.loadDefaultValues();
            }
        });
    },

    get shouldShowAttributeFilter() {
        return (
            this.props.resModel === "product.product" &&
            !!this.props.context?.enable_purchase_attribute_filter
        );
    },

    get attributeChoices() {
        return this.attrState.attributes.map((attr) => ({
            value: attr.id,
            label: attr.name,
        }));
    },

    get templateChoices() {
        return [
            { value: 0, label: this.attributeFilterLabels.templateAll },
            ...this.attrState.templates.map((tmpl) => ({
                value: tmpl.id,
                label: tmpl.name,
            })),
        ];
    },

    get viewProps() {
        const props = { ...super.viewProps };
        if (this.shouldShowAttributeFilter) {
            const extraDomains = [];
            if (this.attrState.templateId) {
                extraDomains.push([["product_tmpl_id", "=", this.attrState.templateId]]);
            }
            if (this.attrState.domain.length) {
                extraDomains.push(this.attrState.domain);
            }
            if (extraDomains.length) {
                props.domain = Domain.and([props.domain, ...extraDomains]).toList();
            }
        }
        return props;
    },

    async loadTemplates() {
        this.attrState.loadingTemplates = true;
        const templates = await this.orm.call(
            "product.template",
            "get_purchase_templates",
            [],
            { context: this.props.context || {} }
        );
        this.attrState.templates = templates || [];
        this.attrState.loadingTemplates = false;
    },

    async loadAttributes() {
        this.attrState.loadingAttributes = true;
        let attributes = [];
        if (this.attrState.templateId) {
            attributes = await this.orm.call(
                "product.template",
                "get_purchase_template_attributes",
                [this.attrState.templateId],
                { context: this.props.context || {} }
            );
        } else {
            attributes = await this.orm.call(
                "product.product",
                "get_purchase_attribute_filters",
                [],
                { context: this.props.context || {} }
            );
        }
        this.attrState.attributes = attributes || [];
        this.attrState.loadingAttributes = false;
    },

    async loadDefaultValues() {
        const attributes = this.attrState.attributes || [];
        if (!attributes.length) {
            return;
        }
        for (const attr of attributes) {
            if (this.attrState.valuesByAttribute[attr.id]?.values?.length) {
                continue;
            }
            await this._fetchValues(attr.id, "", 5);
        }
    },

    async _fetchValues(attributeId, search, limit) {
        const prev = this.attrState.valuesByAttribute[attributeId] || {
            values: [],
            loading: false,
            search: "",
        };
        this.attrState.valuesByAttribute = {
            ...this.attrState.valuesByAttribute,
            [attributeId]: { ...prev, loading: true, search },
        };
        let values = [];
        if (this.attrState.templateId) {
            values = await this.orm.call(
                "product.template",
                "get_purchase_template_attribute_values",
                [this.attrState.templateId, attributeId, search, limit],
                { context: this.props.context || {} }
            );
        } else {
            values = await this.orm.call(
                "product.product",
                "get_purchase_attribute_values",
                [attributeId, search, limit],
                { context: this.props.context || {} }
            );
        }
        const merged = new Map();
        for (const value of prev.values || []) {
            merged.set(value.id, value);
        }
        for (const value of values || []) {
            merged.set(value.id, value);
        }
        this.attrState.valuesByAttribute = {
            ...this.attrState.valuesByAttribute,
            [attributeId]: {
                loading: false,
                search,
                values: Array.from(merged.values()),
            },
        };
    },

    async onTemplateSelected(templateId) {
        const nextTemplateId = templateId ? parseInt(templateId, 10) : null;
        this.attrState.templateId = nextTemplateId || null;
        this.attrState.selections = {};
        this.attrState.appliedRows = [];
        this.attrState.domain = [];
        this.attrState.valuesByAttribute = {};
        await this.loadAttributes();
        await this.loadDefaultValues();
    },

    toggleAttributePanel() {
        this.attrState.open = !this.attrState.open;
    },

    getSelectedValueIds(attributeId) {
        return this.attrState.selections[attributeId] || [];
    },

    getValueChoices(attributeId) {
        const values = this.attrState.valuesByAttribute[attributeId]?.values || [];
        return values.map((value) => ({
            value: value.id,
            label: value.name,
        }));
    },

    async onValueSearch(attributeId, searchString) {
        const search = (searchString || "").trim();
        if (!search) {
            await this._fetchValues(attributeId, "", 5);
            return;
        }
        await this._fetchValues(attributeId, search, 50);
    },

    onValuesSelected(attributeId, valueIds) {
        this.attrState.selections = {
            ...this.attrState.selections,
            [attributeId]: valueIds || [],
        };
        this.applyAttributeFilters({ closePanel: false });
    },

    clearAttributeFilters() {
        this.attrState.selections = {};
        this.attrState.appliedRows = [];
        this.attrState.domain = [];
    },

    applyAttributeFilters({ closePanel = true } = {}) {
        const domain = [];
        const appliedRows = [];
        const attributesById = Object.fromEntries(
            this.attrState.attributes.map((attr) => [attr.id, attr])
        );

        for (const [attributeId, valueIds] of Object.entries(this.attrState.selections)) {
            if (!valueIds.length) {
                continue;
            }
            const attrId = parseInt(attributeId, 10);
            domain.push([
                "product_template_attribute_value_ids.product_attribute_value_id",
                "in",
                valueIds,
            ]);
            const attr = attributesById[attrId];
            const values = this.attrState.valuesByAttribute[attrId]?.values || [];
            const valueNames = values
                .filter((val) => valueIds.includes(val.id))
                .map((val) => val.name);
            appliedRows.push({
                attributeId: attrId,
                attributeName: attr ? attr.name : "",
                values: valueNames,
            });
        }

        this.attrState.domain = domain;
        this.attrState.appliedRows = appliedRows;
        if (closePanel) {
            this.attrState.open = false;
        }
    },
});
