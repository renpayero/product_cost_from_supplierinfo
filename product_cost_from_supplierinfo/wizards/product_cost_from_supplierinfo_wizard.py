# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from collections import Counter, defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import (
    clean_context,
    float_compare,
    float_is_zero,
    format_date,
    format_list,
    formatLang,
    split_every,
)

from ..models.product_cost_from_supplierinfo_batch import SOURCE_SELECTION
from ..models.product_product import PREVIEW_COSTS_KEY

# Products per call to the pricelist engine, which loops products x rules.
PRICE_CHUNK_SIZE = 200
# Products per round of cost writes.
APPLY_CHUNK_SIZE = 200
# Order of the preview lines that have the same warning level.
STATE_RANK = {"update": 0, "unchanged": 1, "skip": 2}
# Window action of the cost updates, for the links of the notifications.
BATCH_ACTION_XMLID = (
    "product_cost_from_supplierinfo.product_cost_from_supplierinfo_batch_action"
)


class ProductCostFromSupplierinfoWizard(models.TransientModel):
    _name = "product.cost.from.supplierinfo.wizard"
    _description = "Cost from Vendor Prices"

    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    source = fields.Selection(
        selection=SOURCE_SELECTION, required=True, default="product"
    )
    supplierinfo_ids = fields.Many2many(
        comodel_name="product.supplierinfo",
        relation="product_cost_from_supplierinfo_wizard_supplierinfo_rel",
        column1="wizard_id",
        column2="supplierinfo_id",
        string="Vendor Prices",
    )
    # Archived products are kept, to show them as skipped in the preview.
    product_ids = fields.Many2many(
        comodel_name="product.product",
        relation="product_cost_from_supplierinfo_wizard_product_rel",
        column1="wizard_id",
        column2="product_id",
        string="Products",
        context={"active_test": False},
    )
    selection_summary = fields.Char(string="Selection", readonly=True)
    selection_truncated = fields.Boolean(readonly=True)
    quantity = fields.Float(
        string="Purchase quantity",
        digits="Product Unit",
        default=1.0,
        help="Quantity used to choose the vendor price of each product: the "
        "prices whose minimum quantity is above it are not used.",
    )
    pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Sale price in",
        domain="[('company_id', 'in', [False, company_id])]",
        help="Optional: also show the current and the new sale price of each "
        "product in this pricelist.",
    )
    threshold = fields.Float(
        string="Flag changes above (%)",
        digits=(16, 2),
        default=30.0,
        help="Products whose cost changes by more than this percentage are "
        "flagged and left unselected, to be checked one by one.",
    )
    state = fields.Selection(
        selection=[("config", "Configure"), ("preview", "Preview")],
        required=True,
        default="config",
    )
    line_ids = fields.One2many(
        comodel_name="product.cost.from.supplierinfo.wizard.line",
        inverse_name="wizard_id",
        string="Lines",
    )
    count_update = fields.Integer(string="To update", compute="_compute_counts")
    count_flagged = fields.Integer(string="Flagged", compute="_compute_counts")
    count_unchanged = fields.Integer(string="No change", compute="_compute_counts")
    count_skip = fields.Integer(string="Skipped", compute="_compute_counts")
    pos_warning = fields.Text(string="Point of sale warning", readonly=True)
    batch_id = fields.Many2one(
        comodel_name="product.cost.from.supplierinfo.batch",
        string="Cost Update",
        readonly=True,
    )

    @api.depends("line_ids.state", "line_ids.flagged")
    def _compute_counts(self):
        for wizard in self:
            states = Counter(wizard.line_ids.mapped("state"))
            wizard.count_update = states["update"]
            wizard.count_unchanged = states["unchanged"]
            wizard.count_skip = states["skip"]
            wizard.count_flagged = len(wizard.line_ids.filtered("flagged"))

    @api.model
    def default_get(self, fields_list):
        # Only who may write on products (product managers) may change costs:
        # refuse before showing anything.
        self.env["product.product"].check_access("write")
        values = super().default_get(fields_list)
        context = self.env.context
        active_model = context.get("active_model")
        active_ids = context.get("active_ids") or []
        if active_model == "product.supplierinfo":
            rows = self.env["product.supplierinfo"].browse(active_ids)
            defaults = {
                "source": "supplierinfo",
                "supplierinfo_ids": [Command.set(rows.ids)],
                "selection_summary": self.env._(
                    "Vendor prices selected: %s", len(rows)
                ),
            }
        elif active_model in ("product.template", "product.product"):
            if active_model == "product.template":
                templates = self.env["product.template"].browse(active_ids)
                products = self._cost_from_supplierinfo_variants(templates)
            else:
                products = self.env["product.product"].browse(active_ids)
                templates = products
            if len(products) == len(templates):
                summary = self.env._("Products selected: %s", len(products))
            else:
                summary = self.env._(
                    "Products selected: %(products)s, variants: %(variants)s",
                    products=len(templates),
                    variants=len(products),
                )
            defaults = {
                "source": "product",
                "product_ids": [Command.set(products.ids)],
                "selection_summary": summary,
            }
        else:
            return values
        limit = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.active_ids_limit", 20000)
        )
        defaults["selection_truncated"] = len(active_ids) >= limit
        values.update(
            {name: value for name, value in defaults.items() if name in fields_list}
        )
        return values

    @api.model
    def _cost_from_supplierinfo_variants(self, templates):
        """Return the variants of ``templates``: the active ones, and the
        archived ones of the templates without active variant, which the
        preview then shows as skipped instead of leaving them out silently."""
        archived = templates.filtered(lambda template: not template.product_variant_ids)
        return (
            templates.product_variant_ids
            | archived.with_context(active_test=False).product_variant_ids
        )

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Cost from Vendor Prices"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    # -------------------------------------------------------------------------
    # Preview
    # -------------------------------------------------------------------------

    def action_preview(self):
        self.ensure_one()
        self._cost_from_supplierinfo_check_values()
        self.line_ids.unlink()
        wizard = self.with_company(self.company_id)
        plans = wizard._cost_from_supplierinfo_plans()
        wizard._cost_from_supplierinfo_add_sale_prices(plans)
        # Lines to update first, then the unchanged ones, then the skipped.
        plans.sort(
            key=lambda plan: STATE_RANK[self._cost_from_supplierinfo_state(plan)]
        )
        # Without the default values the list the wizard comes from may pass.
        Line = self.env["product.cost.from.supplierinfo.wizard.line"].with_context(
            clean_context(self.env.context)
        )
        Line.create(
            [
                wizard._cost_from_supplierinfo_line_vals(plan, sequence)
                for sequence, plan in enumerate(plans)
            ]
        )
        updated = self.env["product.product"].union(
            *(
                plan["product"]
                for plan in plans
                if self._cost_from_supplierinfo_state(plan) == "update"
            )
        )
        self.write(
            {
                "state": "preview",
                "pos_warning": wizard._cost_from_supplierinfo_pos_warning(updated),
            }
        )
        return self._reopen()

    def _cost_from_supplierinfo_check_values(self):
        selection = (
            self.supplierinfo_ids if self.source == "supplierinfo" else self.product_ids
        )
        if not selection:
            raise UserError(self.env._("Select at least one vendor price or product."))
        if float_compare(self.threshold, 0.0, precision_digits=2) < 0:
            raise UserError(self.env._("The threshold cannot be negative."))
        quantity_digits = self.env["decimal.precision"].precision_get("Product Unit")
        if (
            self.source == "product"
            and float_compare(self.quantity, 0.0, precision_digits=quantity_digits) <= 0
        ):
            raise UserError(
                self.env._("The purchase quantity must be greater than zero.")
            )

    def _cost_from_supplierinfo_plans(self):
        """Return one plan (a dict) per product to update: its vendor price,
        its current and new cost, and why it is skipped or flagged."""
        today = fields.Date.context_today(self)
        if self.source == "supplierinfo":
            plans = self._cost_from_supplierinfo_plans_from_rows(today)
        else:
            plans = self._cost_from_supplierinfo_plans_from_products(today)
        rows = self.env["product.supplierinfo"].union(*(plan["row"] for plan in plans))
        no_rate = self._cost_from_supplierinfo_currencies_without_rate(rows.currency_id)
        fiscal_positions = {}
        for plan in plans:
            self._cost_from_supplierinfo_evaluate(
                plan, today, no_rate, fiscal_positions
            )
        return plans

    def _cost_from_supplierinfo_new_plan(self, product, row):
        return {
            "product": product,
            "row": row,
            "skip": False,
            "flags": [],
            "infos": [],
            "state": "skip",
            "current_cost": 0.0,
            "new_cost": 0.0,
            "change_pct": 0.0,
            "current_sale_price": 0.0,
            "new_sale_price": 0.0,
            "sale_change_pct": 0.0,
        }

    @api.model
    def _cost_from_supplierinfo_state(self, plan):
        return "skip" if plan["skip"] else plan["state"]

    def _cost_from_supplierinfo_plans_from_rows(self, today):
        pairs = [
            (row, product)
            for row in self.supplierinfo_ids
            for product in (
                row.product_id
                or self._cost_from_supplierinfo_variants(row.product_tmpl_id)
            )
        ]
        rows_per_product = Counter(product.id for _row, product in pairs)
        plans = []
        for row, product in pairs:
            plan = self._cost_from_supplierinfo_new_plan(product, row)
            if rows_per_product[product.id] > 1:
                plan["skip"] = self.env._(
                    "Vendor prices selected for this product: %s",
                    rows_per_product[product.id],
                )
                plans.append(plan)
                continue
            if (row.date_start and row.date_start > today) or (
                row.date_end and row.date_end < today
            ):
                plan["flags"].append(
                    self.env._(
                        "Vendor price not valid today (%s → %s)",
                        self._cost_from_supplierinfo_format_date(row.date_start),
                        self._cost_from_supplierinfo_format_date(row.date_end),
                    )
                )
            # The cost of a product follows its main vendor: the price of
            # another vendor is checked one by one.
            first = self._cost_from_supplierinfo_first_vendors(product, today, None)
            if first and row.partner_id not in first:
                plan["flags"].append(
                    self.env._(
                        "The main vendor of this product is %s.",
                        format_list(self.env, first.mapped("display_name")),
                    )
                )
            elif len(first) > 1:
                plan["flags"].append(self._cost_from_supplierinfo_tie_flag(first))
            plans.append(plan)
        return plans

    def _cost_from_supplierinfo_plans_from_products(self, today):
        plans = []
        for product in self.product_ids:
            # The vendor price Odoo uses when it replenishes this quantity
            # without a fixed vendor: the first valid row of the Purchase tab
            # of the product, then the lowest price of that vendor. A purchase
            # order does not choose: it always uses its own vendor.
            seller = product._select_seller(
                quantity=self.quantity, date=today, uom_id=product.uom_id
            )
            # _select_seller reads the vendor prices in sudo.
            plan = self._cost_from_supplierinfo_new_plan(
                product, seller.with_env(self.env)
            )
            if not seller:
                plan["skip"] = self._cost_from_supplierinfo_no_seller_reason(
                    product, today
                )
                plans.append(plan)
                continue
            # Odoo breaks a tie by list order (the larger minimum quantity,
            # then the lower price before the discount), and skips the rows
            # not valid today for this quantity: both are checked one by one.
            first = self._cost_from_supplierinfo_first_vendors(
                product, today, self.quantity
            )
            if len(first) > 1:
                plan["flags"].append(self._cost_from_supplierinfo_tie_flag(first))
            # The first vendor ignoring dates and quantities; when it shares
            # the first position, the tie above says why it is not used.
            main = product._prepare_sellers()[:1].partner_id
            if main and main != seller.partner_id and main not in first:
                plan["flags"].append(
                    self.env._(
                        "The first vendor of the product, %s, has no price valid "
                        "today for this quantity; %s is used.",
                        main.display_name,
                        seller.partner_id.display_name,
                    )
                )
            plans.append(plan)
        return plans

    @api.model
    def _cost_from_supplierinfo_first_vendors(self, product, today, quantity):
        """Return the vendors in the first position of the vendor prices of
        ``product`` valid today for ``quantity`` (``None``: for any quantity),
        in the order Odoo uses: the vendors of the rows that have the sequence
        of the first row. Odoo uses the first of them when it replenishes the
        product without a fixed vendor."""
        rows = product._get_filtered_sellers(
            quantity=quantity, date=today, uom_id=product.uom_id
        )
        sequence = rows[:1].sequence
        return rows.filtered(lambda row: row.sequence == sequence).partner_id

    def _cost_from_supplierinfo_tie_flag(self, partners):
        return self.env._(
            "Several vendors share the first position (%s): the vendor was chosen "
            "by list order. Set the order of the vendors of the product.",
            format_list(self.env, partners.mapped("display_name")),
        )

    def _cost_from_supplierinfo_no_seller_reason(self, product, today):
        rows = product.sudo().seller_ids.filtered(
            lambda row: not row.product_id or row.product_id == product
        )
        if not rows:
            return self.env._("No vendor price")
        tiers = product._get_filtered_sellers(
            quantity=None, date=today, uom_id=product.uom_id
        )
        if tiers:
            first = tiers.sorted("min_qty")[:1]
            return self.env._(
                "Vendor prices start at a minimum quantity of %s",
                self._cost_from_supplierinfo_format_qty(
                    first.min_qty, first.product_uom_id
                ),
            )
        company = self.company_id
        company_rows = rows.filtered(
            lambda row: not row.company_id or row.company_id == company
        )
        if company_rows and not company_rows.partner_id.filtered("active"):
            return self.env._("Only archived vendors")
        return self.env._("No vendor price valid today for this company")

    def _cost_from_supplierinfo_currencies_without_rate(self, currencies):
        """Return the currencies of ``currencies`` without any exchange rate for
        the company: Odoo would convert them at 1, which gives a wrong cost."""
        company = self.company_id
        currencies -= company.currency_id
        if not currencies:
            return currencies
        groups = (
            self.env["res.currency.rate"]
            .sudo()
            ._read_group(
                [
                    ("currency_id", "in", currencies.ids),
                    ("company_id", "in", [False, company.root_id.id]),
                ],
                ["currency_id"],
            )
        )
        rated_ids = {currency.id for (currency,) in groups}
        return currencies.filtered(lambda currency: currency.id not in rated_ids)

    def _cost_from_supplierinfo_skip_reason(self, row, product, no_rate):
        company = self.company_id
        price_digits = self.env["decimal.precision"].precision_get("Product Price")
        if not row.partner_id.active:
            return self.env._("Archived vendor")
        if row.company_id and row.company_id != company:
            return self.env._("Vendor price of another company")
        if float_is_zero(row.price, precision_digits=price_digits):
            return self.env._("Vendor price is zero")
        if not (product.active and product.product_tmpl_id.active):
            return self.env._("Archived product")
        if product.company_id and product.company_id not in company.parent_ids:
            return self.env._("Product of another company")
        if not row._cost_from_supplierinfo_uom_compatible(product):
            return self.env._("Incompatible units of measure")
        if row.currency_id in no_rate:
            return self.env._("No exchange rate for %s", row.currency_id.name)
        if product._cost_from_supplierinfo_cost_is_computed():
            return self.env._("Cost method is FIFO/AVCO")
        return False

    def _cost_from_supplierinfo_evaluate(self, plan, today, no_rate, fiscal_positions):
        """Complete ``plan`` with the current and the new cost, its state and
        the reasons to skip or flag it."""
        product, row = plan["product"], plan["row"]
        digits = self.env["decimal.precision"].precision_get("Product Price")
        plan["current_cost"] = product.standard_price
        plan["skip"] = plan["skip"] or self._cost_from_supplierinfo_skip_reason(
            row, product, no_rate
        )
        if plan["skip"]:
            return
        partner = row.partner_id
        if partner.id not in fiscal_positions:
            fiscal_positions[partner.id] = (
                self.env["account.fiscal.position"]
                .sudo()
                ._get_fiscal_position(partner.sudo())
            )
        cost, notes = row._get_cost_from_supplierinfo(
            product,
            self.company_id,
            today,
            fiscal_position=fiscal_positions[partner.id],
        )
        if float_compare(cost, 0.0, precision_digits=digits) < 0:
            plan["skip"] = self.env._("The cost would be negative")
            return
        plan["new_cost"] = cost
        # A minimum of one unit of the product is no minimum for this cost.
        min_qty = row.product_uom_id._compute_quantity(
            row.min_qty, product.uom_id, round=False
        )
        if product.uom_id.compare(min_qty, 1.0) > 0:
            plan["infos"].append(
                self.env._(
                    "Price for a minimum of %s %s",
                    formatLang(self.env, row.min_qty, dp="Product Unit"),
                    row.product_uom_id.name,
                )
            )
        plan["infos"] += notes
        current = plan["current_cost"]
        if not float_compare(cost, current, precision_digits=digits):
            plan["state"] = "unchanged"
            return
        plan["state"] = "update"
        if float_is_zero(current, precision_digits=digits):
            plan["infos"].insert(0, self.env._("No current cost"))
            return
        plan["change_pct"] = self._cost_from_supplierinfo_change_pct(current, cost)
        change = abs(plan["change_pct"])
        if float_compare(change, self.threshold, precision_digits=2) > 0:
            plan["flags"].append(
                self.env._(
                    "Cost changes by %s %%",
                    formatLang(self.env, plan["change_pct"], digits=2),
                )
            )

    def _cost_from_supplierinfo_add_sale_prices(self, plans):
        """Complete ``plans`` with the current and the new sale price in the
        chosen pricelist, the new one computed without writing anything."""
        pricelist = self.pricelist_id
        if not pricelist:
            return
        rounding = pricelist.currency_id.rounding
        priced = [plan for plan in plans if not plan["skip"]]
        Product = self.env["product.product"]
        for chunk in split_every(PRICE_CHUNK_SIZE, priced):
            products = Product.union(*(plan["product"] for plan in chunk))
            current_prices = pricelist._get_products_price(products, 1.0)
            # Only a new cost can give a new price: the price of the unchanged
            # products is not computed again.
            costs = {
                plan["product"].id: plan["new_cost"]
                for plan in chunk
                if plan["state"] == "update"
            }
            new_prices = {}
            if costs:
                planned = Product.browse(list(costs)).with_context(
                    **{PREVIEW_COSTS_KEY: costs}
                )
                new_prices = pricelist._get_products_price(planned, 1.0)
            for plan in chunk:
                current = current_prices[plan["product"].id]
                new = new_prices.get(plan["product"].id, current)
                plan["current_sale_price"] = current
                plan["new_sale_price"] = new
                plan["sale_change_pct"] = self._cost_from_supplierinfo_change_pct(
                    current, new
                )
                if plan["state"] == "update" and not float_compare(
                    current, new, precision_rounding=rounding
                ):
                    plan["infos"].append(
                        self.env._("The sale price does not depend on the cost")
                    )

    def _cost_from_supplierinfo_line_vals(self, plan, sequence):
        row = plan["row"]
        state = self._cost_from_supplierinfo_state(plan)
        if state == "skip":
            messages = [plan["skip"]]
        else:
            messages = plan["flags"] + plan["infos"]
        flagged = state == "update" and bool(plan["flags"])
        if state != "update" or not messages:
            warning_level = "0"
        else:
            warning_level = "2" if flagged else "1"
        return {
            "wizard_id": self.id,
            "sequence": sequence,
            "apply": state == "update" and not flagged,
            "product_id": plan["product"].id,
            "supplierinfo_id": row.id,
            "partner_id": row.partner_id.id,
            "vendor_price": row.price,
            "vendor_currency_id": row.currency_id.id,
            "discount": row.discount,
            "vendor_uom_id": row.product_uom_id.id,
            "current_cost": plan["current_cost"],
            "new_cost": plan["new_cost"],
            "change_pct": plan["change_pct"],
            "current_sale_price": plan["current_sale_price"],
            "new_sale_price": plan["new_sale_price"],
            "sale_change_pct": plan["sale_change_pct"],
            "state": state,
            "flagged": flagged,
            "warning_level": warning_level,
            "message": " · ".join(messages) or False,
        }

    def _cost_from_supplierinfo_pos_warning(self, products):
        """Return the warning about the points of sale of the company whose
        prices depend on the cost, that have an open session and sell some of
        ``products``, or False."""
        if "pos.config" not in self.env or not products.sudo().filtered(
            "available_in_pos"
        ):
            return False
        configs = self.env["product.product"]._cost_from_supplierinfo_pos_configs(
            self.company_id
        )
        configs = configs.filtered(
            lambda config: config.active and config.has_active_session
        )
        if not configs:
            return False
        # Opening the point of sale from the dashboard, or a new session, after
        # last_data_change moved deletes the browser database of the point of
        # sale (point_of_sale/static/src/app/services/data_service.js,
        # loadInitialData), with the orders not yet sent to the server.
        return self.env._(
            "These points of sale have an open session: %s. After this update, "
            "opening one of them from the Point of Sale dashboard, or starting a "
            "new session, reloads all its data and deletes, in that browser, "
            "every order not yet sent to the server: the order in progress, the "
            "open orders not saved for later (with the upload button of the "
            "order) and the paid orders that could not be sent. To get the new "
            "costs, and the prices based on them, finish or save those orders, "
            "then open the point of sale again from the dashboard. Refreshing "
            "the page (F5) does not reload anything.",
            format_list(self.env, configs.mapped("name")),
        )

    @api.model
    def _cost_from_supplierinfo_change_pct(self, old, new):
        return (new - old) / old * 100 if old else 0.0

    def _cost_from_supplierinfo_format_date(self, value):
        return format_date(self.env, value) if value else "…"

    def _cost_from_supplierinfo_format_qty(self, quantity, uom):
        return "%s %s" % (formatLang(self.env, quantity, dp="Product Unit"), uom.name)

    # -------------------------------------------------------------------------
    # Line selection
    # -------------------------------------------------------------------------

    def action_select_all(self):
        self.ensure_one()
        self.line_ids.filtered(lambda line: line.state == "update").write(
            {"apply": True}
        )
        return self._reopen()

    def action_select_none(self):
        self.ensure_one()
        self.line_ids.write({"apply": False})
        return self._reopen()

    def action_unselect_flagged(self):
        self.ensure_one()
        self.line_ids.filtered("flagged").write({"apply": False})
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.line_ids.unlink()
        # The next preview is a new one, that can be applied too.
        self.write({"state": "config", "pos_warning": False, "batch_id": False})
        return self._reopen()

    # -------------------------------------------------------------------------
    # Apply
    # -------------------------------------------------------------------------

    def action_apply(self):
        self.ensure_one()
        close = {"type": "ir.actions.act_window_close"}
        if self.batch_id:
            # This preview was applied already, for instance by a first click
            # whose answer the browser did not wait for: the lines are left as
            # they are.
            return self._cost_from_supplierinfo_notification(
                self.env._("Already applied"),
                self.env._("The costs of this preview were already applied:"),
                "info",
                close,
                batch=self.batch_id,
            )
        if self.state != "preview":
            return self.action_preview()
        self.env["product.product"].check_access("write")
        lines = self.line_ids.filtered(
            lambda line: line.apply and line.state == "update"
        )
        if not lines:
            raise UserError(self.env._("Nothing to apply."))
        company = self.company_id
        digits = self.env["decimal.precision"].precision_get("Product Price")
        Product = self.env["product.product"].with_company(company)
        Line = self.env["product.cost.from.supplierinfo.wizard.line"]
        applied_ids, already_ids, stale_ids, computed_ids = [], [], [], []
        for chunk in split_every(APPLY_CHUNK_SIZE, lines.ids, lines.browse):
            product_ids_by_cost = defaultdict(list)
            for line in chunk:
                product = line.product_id.with_company(company)
                current = product.standard_price
                # The product may have changed since the preview: leave alone
                # the products whose cost Odoo computes now (FIFO, AVCO) and
                # those whose cost changed (another user, a receipt...).
                if product._cost_from_supplierinfo_cost_is_computed():
                    computed_ids.append(line.id)
                elif not float_compare(current, line.new_cost, precision_digits=digits):
                    # Applied already, for instance from another window: there
                    # is nothing to write.
                    already_ids.append(line.id)
                elif float_compare(current, line.current_cost, precision_digits=digits):
                    stale_ids.append(line.id)
                else:
                    product_ids_by_cost[line.new_cost].append(product.id)
                    applied_ids.append(line.id)
            # Written on the variants with the rights of the user, so that Odoo
            # records each change in the cost history (stock_account).
            for cost, product_ids in product_ids_by_cost.items():
                Product.browse(product_ids).write({"standard_price": cost})
            self.env.flush_all()
        for line_ids, message in (
            (stale_ids, self.env._("Cost changed since the preview")),
            (computed_ids, self.env._("Cost method is FIFO/AVCO")),
        ):
            if line_ids:
                Line.browse(line_ids).write(
                    {
                        "state": "skip",
                        "apply": False,
                        "flagged": False,
                        "warning_level": "2",
                        "message": message,
                    }
                )
        counts = []
        if already_ids:
            counts.append(
                self.env._("Already had the new cost: %s.", len(already_ids))
            )
        if stale_ids:
            counts.append(
                self.env._(
                    "Skipped because their cost changed since the preview: %s.",
                    len(stale_ids),
                )
            )
        if computed_ids:
            counts.append(
                self.env._(
                    "Skipped because their cost method is FIFO/AVCO: %s.",
                    len(computed_ids),
                )
            )
        if not applied_ids:
            if stale_ids or computed_ids:
                # Shown again, with the reason on each skipped line.
                return self._cost_from_supplierinfo_notification(
                    self.env._("Nothing was applied"),
                    " ".join([*counts, self.env._("Check the preview again.")]),
                    "warning",
                    self._reopen(),
                )
            return self._cost_from_supplierinfo_notification(
                self.env._("Nothing was applied"),
                self.env._("The selected products already had the new cost."),
                "info",
                close,
            )
        applied = Line.browse(applied_ids)
        self.batch_id = self._cost_from_supplierinfo_create_batch(applied)
        applied.product_id._cost_from_supplierinfo_schedule_pos_refresh(company)
        return self._cost_from_supplierinfo_notification(
            self.env._("Costs updated"),
            " ".join([self.env._("Updated costs: %s.", len(applied)), *counts]),
            "success",
            close,
            batch=self.batch_id,
        )

    def _cost_from_supplierinfo_create_batch(self, applied):
        unchanged = self.line_ids.filtered(lambda line: line.state == "unchanged")
        # sudo: the history is only written by this module.
        return (
            self.env["product.cost.from.supplierinfo.batch"]
            .sudo()
            .with_context(clean_context(self.env.context))
            .create(
                {
                    "company_id": self.company_id.id,
                    "user_id": self.env.uid,
                    "source": self.source,
                    "pricelist_id": self.pricelist_id.id,
                    "count_updated": len(applied),
                    "count_unchanged": len(unchanged),
                    "count_skipped": len(self.line_ids) - len(applied) - len(unchanged),
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": line.product_id.id,
                                "supplierinfo_id": line.supplierinfo_id.id,
                                "partner_id": line.partner_id.id,
                                "old_cost": line.current_cost,
                                "new_cost": line.new_cost,
                            }
                        )
                        for line in applied
                    ],
                }
            )
        )

    def _cost_from_supplierinfo_notification(
        self, title, message, kind, next_action, batch=None
    ):
        """Return the action that shows a notification, then ``next_action``;
        with ``batch``, the message ends with a link to that cost update."""
        params = {
            "title": title,
            "message": message,
            "type": kind,
            "sticky": False,
            "next": next_action,
        }
        if batch:
            # The message is a format string for the link.
            params["message"] = "%s %%s" % message.replace("%", "%%")
            params["links"] = [
                {
                    "label": batch.name,
                    "url": f"/odoo/action-{BATCH_ACTION_XMLID}/{batch.id}",
                }
            ]
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": params,
        }


class ProductCostFromSupplierinfoWizardLine(models.TransientModel):
    _name = "product.cost.from.supplierinfo.wizard.line"
    _description = "Cost from Vendor Prices Line"
    _order = "warning_level desc, sequence, id"

    wizard_id = fields.Many2one(
        comodel_name="product.cost.from.supplierinfo.wizard",
        required=True,
        index=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(readonly=True)
    apply = fields.Boolean()
    product_id = fields.Many2one(
        comodel_name="product.product",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id")
    default_code = fields.Char(related="product_id.default_code")
    supplierinfo_id = fields.Many2one(
        comodel_name="product.supplierinfo",
        string="Vendor Price",
        readonly=True,
        ondelete="set null",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner", string="Vendor", readonly=True
    )
    vendor_price = fields.Float(
        string="Vendor price", min_display_digits="Product Price", readonly=True
    )
    vendor_currency_id = fields.Many2one(
        comodel_name="res.currency", string="Vendor currency", readonly=True
    )
    discount = fields.Float(string="Discount (%)", digits="Discount", readonly=True)
    vendor_uom_id = fields.Many2one(
        comodel_name="uom.uom", string="Vendor unit", readonly=True
    )
    current_cost = fields.Float(
        string="Current cost", min_display_digits="Product Price", readonly=True
    )
    new_cost = fields.Float(
        string="New cost", min_display_digits="Product Price", readonly=True
    )
    change_pct = fields.Float(string="Change (%)", digits=(16, 2), readonly=True)
    current_sale_price = fields.Float(
        string="Current sale price", min_display_digits="Product Price", readonly=True
    )
    new_sale_price = fields.Float(
        string="New sale price", min_display_digits="Product Price", readonly=True
    )
    sale_change_pct = fields.Float(
        string="Sale price change (%)", digits=(16, 2), readonly=True
    )
    state = fields.Selection(
        selection=[("update", "Update"), ("unchanged", "No change"), ("skip", "Skip")],
        string="Action",
        required=True,
        readonly=True,
        default="skip",
    )
    flagged = fields.Boolean(readonly=True)
    warning_level = fields.Selection(
        selection=[("0", "None"), ("1", "Info"), ("2", "Warning")],
        required=True,
        readonly=True,
        default="0",
    )
    message = fields.Char(readonly=True)
