# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

import psycopg2.errors

from odoo import SUPERUSER_ID, api, fields, models

_logger = logging.getLogger(__name__)

# Context key holding the planned costs ({product id: cost}) while the preview
# computes the new sale prices. Nothing is written with it.
PREVIEW_COSTS_KEY = "cost_from_supplierinfo_costs"
# Key of the companies whose points of sale reload their data after the
# commit of the current transaction (shared data of the post-commit hooks).
POS_REFRESH_KEY = "product_cost_from_supplierinfo.pos_refresh_company_ids"
# Times the post-commit refresh is tried again when another transaction
# updated the same point of sale configurations at the same time.
POS_REFRESH_RETRIES = 3
POS_REFRESH_RETRY_ERRORS = (
    psycopg2.errors.SerializationFailure,
    psycopg2.errors.DeadlockDetected,
)
# How far a chain of pricelists based on other pricelists is followed.
BASE_PRICELIST_DEPTH = 10


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _price_compute(
        self, price_type, uom=None, currency=None, company=None, date=False
    ):
        prices = super()._price_compute(
            price_type, uom=uom, currency=currency, company=company, date=date
        )
        costs = self.env.context.get(PREVIEW_COSTS_KEY)
        if price_type != "standard_price" or not costs:
            return prices
        # Preview of the sale prices: the planned cost replaces the current
        # one, converted like core does with the current one.
        company = company or self.env.company
        date = date or fields.Date.context_today(self)
        for product in self.with_company(company).sudo():
            if product.id not in costs:
                continue
            price = costs[product.id]
            if uom:
                price = product.uom_id._compute_price(price, uom)
            if currency:
                price = product.cost_currency_id._convert(
                    price, currency, company, date
                )
            prices[product.id] = price
        return prices

    def _cost_from_supplierinfo_cost_is_computed(self):
        """Return whether Odoo computes the cost of this product in the
        current company: with stock_account, the cost of the FIFO and AVCO
        cost methods comes from the receipts, so it is not written by hand."""
        self.ensure_one()
        return "cost_method" in self._fields and self.cost_method != "standard"

    @api.model
    def _cost_from_supplierinfo_pos_configs(self, companies):
        """Return the point of sale configurations of ``companies``, archived
        ones included, whose prices can depend on the cost of the products:
        the till applies a pricelist with a rule based on the cost, or a
        pricelist based on such a pricelist (at any depth up to
        BASE_PRICELIST_DEPTH), as default or available pricelist when it uses
        pricelists, or through one of its presets when it uses presets. A till
        without pricelists sells at the sales price of the product. An archived
        configuration keeps its data in the browser and uses it if it is
        restored. Read with sudo: the user who changes the costs may have no
        rights on the point of sale."""
        if "pos.config" not in self.env:
            return None
        Config = self.env["pos.config"].sudo()
        # Pricelists whose prices depend on the cost, directly or not.
        Item = self.env["product.pricelist.item"].sudo()
        groups = Item._read_group([("base", "=", "standard_price")], ["pricelist_id"])
        affected = {pricelist.id for (pricelist,) in groups if pricelist}
        todo = set(affected)
        for _level in range(BASE_PRICELIST_DEPTH):
            if not todo:
                break
            groups = Item._read_group(
                [("base", "=", "pricelist"), ("base_pricelist_id", "in", list(todo))],
                ["pricelist_id"],
            )
            todo = {pricelist.id for (pricelist,) in groups if pricelist} - affected
            affected |= todo
        if not affected or not companies:
            return Config
        has_presets = all(
            fname in Config._fields
            for fname in ("use_presets", "available_preset_ids", "default_preset_id")
        )

        def applied_pricelists(config):
            # Without "use a pricelist", the till ignores the default
            # pricelist, and it ignores the presets unless it uses them.
            pricelists = self.env["product.pricelist"]
            if config.use_pricelist:
                pricelists |= config.available_pricelist_ids | config.pricelist_id
            if has_presets and config.use_presets:
                presets = config.available_preset_ids | config.default_preset_id
                pricelists |= presets.pricelist_id
            return pricelists

        configs = Config.with_context(active_test=False).search(
            [("company_id", "in", companies.ids)]
        )
        # Read the pricelists of the configurations as the point of sale
        # loads them: the archived ones are left out.
        configs = configs.with_context(active_test=True)
        return configs.filtered(
            lambda config: affected.intersection(applied_pricelists(config).ids)
        )

    def _cost_from_supplierinfo_schedule_pos_refresh(self, company):
        """Make the points of sale of ``company`` whose prices depend on the
        cost reload all their data after the commit, when ``self`` holds
        products sold there.

        A point of sale keeps its data in the browser and only reloads, in
        part, the product templates that changed: a cost written on a variant
        never reaches it. Moving ``last_data_change`` makes it reload
        everything the next time it is opened. It is done once per transaction,
        after the commit and in a new cursor, so that a point of sale that
        loads its data meanwhile cannot keep the old costs.
        """
        if "pos.config" not in self.env or not self.sudo().filtered("available_in_pos"):
            return
        postcommit = self.env.cr.postcommit
        company_ids = postcommit.data.get(POS_REFRESH_KEY)
        if company_ids is None:
            company_ids = postcommit.data[POS_REFRESH_KEY] = set()
            registry = self.env.registry

            @postcommit.add
            def _cost_from_supplierinfo_refresh_pos():
                for attempt in range(POS_REFRESH_RETRIES + 1):
                    try:
                        with registry.cursor() as cr:
                            env = api.Environment(cr, SUPERUSER_ID, {})
                            Product = env["product.product"]
                            companies = env["res.company"].browse(list(company_ids))
                            Product._cost_from_supplierinfo_pos_refresh_now(
                                Product._cost_from_supplierinfo_pos_configs(companies)
                            )
                        return
                    except POS_REFRESH_RETRY_ERRORS:
                        # Another refresh updated the same configurations:
                        # try again with a new snapshot of the database.
                        if attempt < POS_REFRESH_RETRIES:
                            continue
                        _logger.exception(
                            "Could not make the points of sale reload their data "
                            "after a cost update (companies %s)",
                            sorted(company_ids),
                        )
                    except Exception:
                        _logger.exception(
                            "Could not make the points of sale reload their data "
                            "after a cost update (companies %s)",
                            sorted(company_ids),
                        )
                        return

        company_ids.add(company.id)

    @api.model
    def _cost_from_supplierinfo_pos_refresh_now(self, configs):
        """Make ``configs`` reload all their data the next time they open."""
        if "pos.config" not in self.env or not configs:
            return
        configs = configs.sudo()
        # Recompute the stored field instead of writing on pos.config, whose
        # write() may install modules and change groups.
        self.env.add_to_compute(configs._fields["last_data_change"], configs)
        configs._recompute_recordset(["last_data_change"])
