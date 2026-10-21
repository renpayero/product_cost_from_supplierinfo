# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests.common import new_test_user

from odoo.addons.base.tests.common import BaseCommon


class CostFromSupplierinfoCommon(BaseCommon):
    """Fixtures: three vendors (C is archived by the tests that need it),
    purchase taxes with and without accounts, a foreign currency, a "Box of
    12" unit, a cost-based pricelist with a derived one, and products with
    their vendor prices.

    The company currency is the one BaseCommon sets (USD); EUR is the foreign
    currency, at 2 USD per EUR.

    The fixtures are created as the superuser, and the tests run as a product
    manager who is also a purchase user (``cls.manager``), the users the
    actions are for: what a test needs from an administrator (users, taxes,
    currencies, the cost history...) is done in sudo explicitly.
    """

    @classmethod
    def default_env_context(cls):
        # The tests check English texts, also those of Odoo, whatever the
        # language of the database and of its users.
        return {**super().default_env_context(), "lang": "en_US"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.price_digits = cls.env["decimal.precision"].precision_get("Product Price")
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_box = cls.env["uom.uom"].create(
            {
                "name": "Box of 12",
                "relative_factor": 12.0,
                "relative_uom_id": cls.uom_unit.id,
            }
        )
        cls.currency_eur = cls.setup_other_currency("EUR", rates=[("2000-01-01", 0.5)])
        cls.company_b = cls._create_company(name="Company B")
        cls.vendor_a, cls.vendor_b, cls.vendor_c = cls.env["res.partner"].create(
            [{"name": "Vendor A"}, {"name": "Vendor B"}, {"name": "Vendor C"}]
        )
        cls._setup_taxes()

        cls.pricelist_main = cls.env["product.pricelist"].create(
            {
                "name": "Main",
                "item_ids": [
                    Command.create(
                        {
                            "applied_on": "3_global",
                            "compute_price": "formula",
                            "base": "standard_price",
                            "price_discount": -75.0,
                        }
                    )
                ],
            }
        )
        cls.pricelist_cash = cls.env["product.pricelist"].create(
            {
                "name": "Cash",
                "item_ids": [
                    Command.create(
                        {
                            "applied_on": "3_global",
                            "compute_price": "percentage",
                            "base": "pricelist",
                            "base_pricelist_id": cls.pricelist_main.id,
                            "percent_price": 27.0,
                        }
                    )
                ],
            }
        )

        # Mixer: vendor A first (100 at 10 % off), vendor B second.
        cls.product_mixer = cls._create_product(
            "Mixer Tap",
            cost=80.0,
            sellers=[
                {"partner_id": cls.vendor_a.id, "price": 100.0, "discount": 10.0},
                {"partner_id": cls.vendor_b.id, "price": 95.0, "sequence": 2},
            ],
        )
        cls.row_mixer_a = cls._row(cls.product_mixer, cls.vendor_a)
        cls.row_mixer_b = cls._row(cls.product_mixer, cls.vendor_b)
        # Basin: its cost goes up by 35 %.
        cls.product_basin = cls._create_product(
            "Basin",
            cost=100.0,
            sellers=[{"partner_id": cls.vendor_a.id, "price": 135.0}],
        )
        cls.row_basin = cls._row(cls.product_basin, cls.vendor_a)
        # Shower head: two variants, a row for the template (vendor A, first
        # for both variants) and one for the black variant only (vendor B,
        # second).
        cls.attribute_finish = cls.env["product.attribute"].create(
            {
                "name": "Finish",
                "value_ids": [
                    Command.create({"name": "Chrome"}),
                    Command.create({"name": "Black"}),
                ],
            }
        )
        values = cls.attribute_finish.value_ids
        cls.template_shower = cls.env["product.template"].create(
            {
                "name": "Shower Head",
                "uom_id": cls.uom_unit.id,
                "supplier_taxes_id": [Command.clear()],
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": cls.attribute_finish.id,
                            "value_ids": [Command.set(values.ids)],
                        }
                    )
                ],
            }
        )
        variants = cls.template_shower.product_variant_ids
        cls.shower_chrome = variants.filtered(
            lambda variant: values[0]
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        cls.shower_black = variants - cls.shower_chrome
        variants.write({"standard_price": 40.0})
        cls.row_shower = cls._create_row(cls.template_shower, cls.vendor_a, 50.0)
        cls.row_shower_black = cls._create_row(
            cls.template_shower,
            cls.vendor_b,
            45.0,
            product_id=cls.shower_black.id,
            sequence=2,
        )

        # From here on, the tests run as a product manager.
        cls.manager = new_test_user(
            cls.env,
            login="cost_manager",
            groups="base.group_user,product.group_product_manager,"
            "purchase.group_purchase_user",
            company_id=cls.company.id,
            company_ids=[Command.set((cls.company | cls.company_b).ids)],
        )
        cls.env = cls.env(user=cls.manager)
        cls.Wizard = cls.env["product.cost.from.supplierinfo.wizard"]
        cls.Batch = cls.env["product.cost.from.supplierinfo.batch"]
        cls.today = fields.Date.context_today(cls.Wizard)

    @classmethod
    def _setup_taxes(cls):
        company = cls.company
        cls.country = (
            company.account_fiscal_country_id
            or company.country_id
            or cls.env.ref("base.us")
        )
        cls.tax_group = cls.env["account.tax.group"].create(
            {
                "name": "Test VAT",
                "company_id": company.id,
                "country_id": cls.country.id,
            }
        )
        cls.tax_account = cls.env["account.account"].create(
            {
                "name": "Test VAT receivable",
                "code": "PCFS1181",
                "account_type": "asset_current",
            }
        )
        cls.tax_21 = cls._create_tax("Test VAT 21%", 21.0)
        cls.tax_21_included = cls._create_tax(
            "Test VAT 21% included", 21.0, included=True
        )
        cls.tax_half_deductible = cls._create_tax(
            "Test VAT 21% half deductible", 21.0, deductible=50.0
        )

    @classmethod
    def _create_tax(cls, name, amount, included=False, deductible=100.0, **values):
        """Create a purchase tax; ``deductible`` is the percentage of the tax
        amount booked on an account, the rest has no account (non-deductible)."""

        def distribution():
            lines = [Command.create({"repartition_type": "base"})]
            if deductible:
                lines.append(
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": deductible,
                            "account_id": cls.tax_account.id,
                        }
                    )
                )
            if deductible < 100.0:
                lines.append(
                    Command.create(
                        {
                            "repartition_type": "tax",
                            "factor_percent": 100.0 - deductible,
                        }
                    )
                )
            return lines

        # sudo: an accountant creates the taxes, also for the tests.
        return cls.env["account.tax"].sudo().create(
            {
                "name": name,
                "amount_type": "percent",
                "amount": amount,
                "type_tax_use": "purchase",
                "price_include_override": (
                    "tax_included" if included else "tax_excluded"
                ),
                "company_id": cls.company.id,
                "country_id": cls.country.id,
                "tax_group_id": cls.tax_group.id,
                "invoice_repartition_line_ids": distribution(),
                "refund_repartition_line_ids": distribution(),
                **values,
            }
        )

    @classmethod
    def _create_product(cls, name, cost=0.0, sellers=(), **values):
        return cls.env["product.product"].create(
            {
                "name": name,
                "standard_price": cost,
                "uom_id": cls.uom_unit.id,
                # Products get the company default purchase tax otherwise.
                "supplier_taxes_id": [Command.clear()],
                "seller_ids": [Command.create(dict(seller)) for seller in sellers],
                **values,
            }
        )

    @classmethod
    def _create_row(cls, product, partner, price, **values):
        """Create a vendor price for ``product`` (a template or a variant)."""
        if product._name == "product.product":
            product = product.product_tmpl_id
        return cls.env["product.supplierinfo"].create(
            {
                "partner_id": partner.id,
                "product_tmpl_id": product.id,
                "price": price,
                **values,
            }
        )

    @classmethod
    def _row(cls, product, partner):
        return product.seller_ids.filtered(lambda row: row.partner_id == partner)

    def _wizard(self, records, companies=None, **values):
        """Open the wizard from ``records``, as the action of their list does;
        ``companies`` are the companies enabled in the company switcher."""
        context = {"active_model": records._name, "active_ids": records.ids}
        if companies:
            context["allowed_company_ids"] = companies.ids
        return self.Wizard.with_context(**context).create(values)

    def _preview(self, records, companies=None, **values):
        wizard = self._wizard(records, companies=companies, **values)
        wizard.action_preview()
        return wizard

    def _apply(self, records, **values):
        """Preview and apply, and return the cost update (batch) created."""
        wizard = self._preview(records, **values)
        wizard.action_apply()
        return wizard.batch_id

    def _line(self, wizard, product):
        return wizard.line_ids.filtered(lambda line: line.product_id == product)

    def _cost(self, product, company=None):
        return product.with_company(company or self.company).standard_price

    def _has_stock_account(self):
        return "product.value" in self.env

    def _cost_history(self, product):
        # sudo: only inventory administrators read the cost history.
        return self.env["product.value"].sudo().search(
            [("product_id", "=", product.id)], order="id desc"
        )

    def _cost_history_count(self, product):
        return len(self._cost_history(product))

    @contextmanager
    def _capture_cost_writes(self):
        """Yield the list of the product ids whose cost is written meanwhile."""
        written = []
        Product = type(self.env["product.product"])
        write = Product.write

        def write_and_capture(records, vals):
            if "standard_price" in vals:
                written.extend(records.ids)
            return write(records, vals)

        with patch.object(Product, "write", write_and_capture):
            yield written
