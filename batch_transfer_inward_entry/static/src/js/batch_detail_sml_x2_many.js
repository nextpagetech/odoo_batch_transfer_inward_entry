/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Domain } from "@web/core/domain";
import { useService } from "@web/core/utils/hooks";
import { useOpenMany2XRecord, useSelectCreate } from "@web/views/fields/relational_utils";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

export class BatchDetailSMLX2ManyField extends X2ManyField {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dirtyQuantsData = new Map();
        const selectCreate = useSelectCreate({
            resModel: "stock.quant",
            activeActions: this.activeActions,
            onSelected: (resIds) => this.selectRecord(resIds),
            onCreateEdit: () => this.createOpenRecord(),
        });
        this.selectCreate = (params) => selectCreate(params);
        this.openQuantRecord = useOpenMany2XRecord({
            resModel: "stock.quant",
            activeActions: this.activeActions,
            onRecordSaved: (record) => this.selectRecord([record.resId]),
            fieldString: this.props.string,
            is2Many: true,
        });
    }

    async onAdd({ context } = {}) {
        if (!this.props.record.data.show_quant) {
            return super.onAdd(...arguments);
        }
        await this.updateDirtyQuantsData();
        context = {
            ...context,
            single_product: true,
            list_view_ref: "stock.view_stock_quant_tree_simple",
            search_default_on_hand: true,
            search_default_in_stock: true,
        };
        const productId = this.props.record.data.product_id?.[0];
        const productName = this.props.record.data.product_id?.[1] || "";
        const sourceLocationId = this.props.context.default_location_id;
        const title = _t("Add line: %s", productName);
        let domain = Domain.and([
            [["product_id", "=", productId]],
            [["location_id", "child_of", sourceLocationId]],
        ]).toList();
        if (this.dirtyQuantsData.size) {
            const notFullyUsed = [];
            const fullyUsed = [];
            for (const [quantId, quantData] of this.dirtyQuantsData.entries()) {
                if (quantData.available_quantity > 0) {
                    notFullyUsed.push(quantId);
                } else {
                    fullyUsed.push(quantId);
                }
            }
            if (fullyUsed.length) {
                domain = Domain.and([domain, [["id", "not in", fullyUsed]]]).toList();
            }
            if (notFullyUsed.length) {
                domain = Domain.or([domain, [["id", "in", notFullyUsed]]]).toList();
            }
        }
        return this.selectCreate({ domain, context, title });
    }

    async updateDirtyQuantsData() {
        this.dirtyQuantsData.clear();
        const usedByQuant = new Map();
        for (const line of this.props.record.data.move_line_ids?.records || []) {
            const quantId = line?.data?.quant_id?.[0];
            if (!quantId) {
                continue;
            }
            const qty = Number(line?.data?.quantity) || 0;
            usedByQuant.set(quantId, (usedByQuant.get(quantId) || 0) + qty);
        }
        const quantIds = [...usedByQuant.keys()];
        if (!quantIds.length) {
            return;
        }
        const quantRows = await this.orm.read("stock.quant", quantIds, ["available_quantity"]);
        for (const row of quantRows) {
            this.dirtyQuantsData.set(row.id, {
                available_quantity: (Number(row.available_quantity) || 0) - (usedByQuant.get(row.id) || 0),
            });
        }
    }

    async selectRecord(resIds) {
        if (!resIds?.length) {
            return;
        }
        const quantId = resIds[0];
        let available = this.dirtyQuantsData.get(quantId)?.available_quantity;
        if (available === undefined) {
            const quantData = await this.orm.read(
                "stock.quant",
                [quantId],
                ["available_quantity"],
            );
            available = Number(quantData?.[0]?.available_quantity) || 0;
        }
        const demand = this.props.record.data.product_uom_qty || 0;
        const already = (this.props.record.data.move_line_ids?.records || [])
            .map((line) => Number(line.data.quantity) || 0)
            .reduce((sum, qty) => sum + qty, 0);
        const remaining = Math.max(demand - already, 0);
        const defaultQuantity = remaining > 0 ? Math.min(Math.max(available, 0), remaining) : 0;

        const params = {
            context: {
                default_quant_id: quantId,
                default_quantity: defaultQuantity,
            },
        };
        this.list.addNewRecord(params).then((record) => {
            // Keep row to let user edit quantity/lot after stock selection.
            record.dirty = true;
        });
    }

    createOpenRecord() {
        const activeElement = document.activeElement;
        this.openQuantRecord({
            context: {
                ...this.props.context,
                form_view_ref: "stock.view_stock_quant_form",
            },
            immediate: true,
            onClose: () => {
                if (activeElement) {
                    activeElement.focus();
                }
            },
        });
    }
}

export const batchDetailSmlX2ManyField = {
    ...x2ManyField,
    component: BatchDetailSMLX2ManyField,
};

registry.category("fields").add("bti_sml_x2_many", batchDetailSmlX2ManyField);
