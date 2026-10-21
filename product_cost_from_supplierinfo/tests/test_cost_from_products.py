# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from odoo.tools import format_list

from ..models.product_product import PREVIEW_COSTS_KEY
from .common import CostFromSupplierinfoCommon


@tagged("post_install", "-at_install")
class TestCostFromProducts(CostFromSupplierinfoCommon):
    def _seller(self, partner, price, **values):
        return {"partner_id": partner.id, "price": price, **values}

    def test_defaults_from_templates_and_variants(self):
        templates = self.product_mixer.product_tmpl_id | self.template_shower
        wizard = self._wizard(templates)
        self.assertEqual(wizard.source, "product")
        self.assertEqual(
            wizard.product_ids,
            self.product_mixer | self.shower_chrome | self.shower_black,
        )
        self.assertEqual(
            wizard.selection_summary, "Products selected: 2, variants: 3"
        )
        wizard = self._wizard(self.shower_black | self.product_mixer)
        self.assertEqual(wizard.product_ids, self.shower_black | self.product_mixer)
        self.assertEqual(wizard.selection_summary, "Products selected: 2")

    def test_archived_template_is_shown_skipped(self):
        product = self._create_product(
            "Discontinued", cost=10.0, sellers=[self._seller(self.vendor_a, 20.0)]
        )
        product.action_archive()
        wizard = self._preview(product.product_tmpl_id)
        self.assertEqual(wizard.product_ids, product)
        self.assertEqual(self._line(wizard, product).message, "Archived product")

    def test_main_vendor_by_sequence(self):
        # Vendor B comes first by sequence, although vendor A is cheaper.
        product = self._create_product(
            "Drain",
            cost=50.0,
            sellers=[
                self._seller(self.vendor_a, 55.0, sequence=2),
                self._seller(self.vendor_b, 60.0, sequence=1),
            ],
        )
        seller = product._select_seller(quantity=1.0)
        self.assertEqual(seller.partner_id, self.vendor_b)
        line = self._line(self._preview(product), product)
        self.assertEqual(line.supplierinfo_id, seller)
        self.assertEqual(line.partner_id, self.vendor_b)
        self.assertAlmostEqual(line.new_cost, 60.0)
        # Distinct sequences: the first vendor is clear, nothing to check.
        self.assertRecordValues(
            line, [{"flagged": False, "apply": True, "message": False}]
        )

    def test_vendors_sharing_the_first_position(self):
        # Same sequence: Odoo takes the lower price before the discount
        # (vendor B, 80), not the lower net price (vendor A, 100 at 40 % off).
        product = self._create_product(
            "Faucet",
            cost=70.0,
            sellers=[
                self._seller(self.vendor_a, 100.0, discount=40.0),
                self._seller(self.vendor_b, 80.0),
            ],
        )
        line = self._line(self._preview(product), product)
        self.assertRecordValues(
            line,
            [
                {
                    "partner_id": self.vendor_b.id,
                    "new_cost": 80.0,
                    "state": "update",
                    "flagged": True,
                    "apply": False,
                    "warning_level": "2",
                }
            ],
        )
        self.assertEqual(
            line.message,
            "Several vendors share the first position (%s): the vendor was chosen "
            "by list order. Set the order of the vendors of the product."
            % format_list(self.env, ["Vendor B", "Vendor A"]),
        )

    def test_first_vendor_without_a_valid_price(self):
        product = self._create_product(
            "Angle Valve",
            cost=50.0,
            sellers=[
                self._seller(self.vendor_a, 55.0, date_end="2020-01-31"),
                self._seller(self.vendor_b, 60.0, sequence=2),
            ],
        )
        line = self._line(self._preview(product), product)
        self.assertRecordValues(
            line,
            [
                {
                    "partner_id": self.vendor_b.id,
                    "new_cost": 60.0,
                    "flagged": True,
                    "apply": False,
                    "warning_level": "2",
                    "message": "The first vendor of the product, Vendor A, has no "
                    "price valid today for this quantity; Vendor B is used.",
                }
            ],
        )

    def test_quantity_tiers(self):
        product = self._create_product(
            "Pipe",
            cost=50.0,
            sellers=[
                self._seller(self.vendor_a, 50.0),
                self._seller(self.vendor_a, 40.0, min_qty=100.0),
            ],
        )
        line = self._line(self._preview(product), product)
        self.assertRecordValues(line, [{"state": "unchanged", "new_cost": 50.0}])
        line = self._line(self._preview(product, quantity=100.0), product)
        self.assertRecordValues(line, [{"state": "update", "new_cost": 40.0}])
        self.assertTrue(line.message.startswith("Price for a minimum of 100"))

    def test_only_minimum_quantity_prices(self):
        product = self._create_product(
            "Bulk Screws", sellers=[self._seller(self.vendor_a, 1.0, min_qty=500.0)]
        )
        line = self._line(self._preview(product), product)
        self.assertEqual(line.state, "skip")
        self.assertTrue(
            line.message.startswith("Vendor prices start at a minimum quantity of 500")
        )

    def test_only_archived_vendors(self):
        product = self._create_product(
            "Legacy Valve", sellers=[self._seller(self.vendor_c, 10.0)]
        )
        self.vendor_c.action_archive()
        line = self._line(self._preview(product), product)
        self.assertEqual(line.message, "Only archived vendors")

    def test_no_vendor_price(self):
        product = self._create_product("Handmade Item")
        line = self._line(self._preview(product), product)
        self.assertRecordValues(line, [{"state": "skip", "message": "No vendor price"}])

    def test_no_vendor_price_valid_today(self):
        expired = self._create_product(
            "Expired Item",
            sellers=[self._seller(self.vendor_a, 10.0, date_end="2020-01-31")],
        )
        other_company = self._create_product(
            "Company B Item",
            sellers=[self._seller(self.vendor_a, 10.0, company_id=self.company_b.id)],
        )
        wizard = self._preview(expired | other_company)
        for product in expired | other_company:
            with self.subTest(product=product.name):
                self.assertEqual(
                    self._line(wizard, product).message,
                    "No vendor price valid today for this company",
                )

    def test_other_company_rows_are_ignored(self):
        product = self._create_product(
            "Shared Item",
            cost=10.0,
            sellers=[
                self._seller(self.vendor_b, 5.0, company_id=self.company_b.id),
                self._seller(self.vendor_a, 12.0, sequence=5),
            ],
        )
        line = self._line(self._preview(product), product)
        self.assertEqual(line.partner_id, self.vendor_a)
        self.assertAlmostEqual(line.new_cost, 12.0)

    def test_zero_price_of_the_main_vendor(self):
        product = self._create_product(
            "Gift", cost=5.0, sellers=[self._seller(self.vendor_a, 0.0)]
        )
        line = self._line(self._preview(product), product)
        self.assertEqual(line.message, "Vendor price is zero")

    def test_non_standard_cost_method_is_skipped(self):
        if "cost_method" not in self.env["product.template"]._fields:
            self.skipTest("stock_account is not installed")
        category = self.env["product.category"].create(
            {"name": "Average Cost", "property_cost_method": "average"}
        )
        product = self._create_product(
            "Average Item",
            cost=10.0,
            categ_id=category.id,
            sellers=[self._seller(self.vendor_a, 12.0)],
        )
        line = self._line(self._preview(product), product)
        self.assertRecordValues(
            line,
            [{"state": "skip", "apply": False, "message": "Cost method is FIFO/AVCO"}],
        )

    def test_sale_price_preview_matches_engine(self):
        wizard = self._preview(self.product_mixer, pricelist_id=self.pricelist_main.id)
        line = self._line(wizard, self.product_mixer)
        self.assertAlmostEqual(line.current_sale_price, 140.0)
        self.assertAlmostEqual(line.new_sale_price, 157.5)
        self.assertAlmostEqual(line.sale_change_pct, 12.5)
        cash_line = self._line(
            self._preview(self.product_mixer, pricelist_id=self.pricelist_cash.id),
            self.product_mixer,
        )
        wizard.action_apply()
        self.assertAlmostEqual(
            line.new_sale_price,
            self.pricelist_main._get_product_price(self.product_mixer, 1.0),
        )
        self.assertAlmostEqual(
            cash_line.new_sale_price,
            self.pricelist_cash._get_product_price(self.product_mixer, 1.0),
        )
        self.assertAlmostEqual(cash_line.new_sale_price, 157.5 * 0.73)

    def test_sale_price_not_based_on_cost(self):
        fixed = self.env["product.pricelist"].create(
            {
                "name": "Fixed",
                "item_ids": [
                    Command.create(
                        {
                            "applied_on": "3_global",
                            "compute_price": "fixed",
                            "fixed_price": 99.0,
                        }
                    )
                ],
            }
        )
        line = self._line(
            self._preview(self.product_mixer, pricelist_id=fixed.id),
            self.product_mixer,
        )
        self.assertAlmostEqual(line.current_sale_price, 99.0)
        self.assertAlmostEqual(line.new_sale_price, 99.0)
        self.assertEqual(line.message, "The sale price does not depend on the cost")
        self.assertEqual(line.warning_level, "1")

    def test_preview_has_no_side_effects(self):
        history = self._has_stock_account() and self._cost_history_count(
            self.product_mixer
        )
        batches = self.Batch.search_count([])
        with self._capture_cost_writes() as written:
            self._preview(
                self.product_mixer | self.product_basin,
                pricelist_id=self.pricelist_cash.id,
            )
        self.assertFalse(written)
        self.assertAlmostEqual(self._cost(self.product_mixer), 80.0)
        self.assertEqual(self.Batch.search_count([]), batches)
        if self._has_stock_account():
            self.assertEqual(self._cost_history_count(self.product_mixer), history)
        self.assertAlmostEqual(
            self.pricelist_main._get_product_price(self.product_mixer, 1.0), 140.0
        )

    def test_price_compute_override(self):
        product = self.product_mixer
        costs_key = "cost_from_supplierinfo_costs"
        self.assertAlmostEqual(
            product._price_compute("standard_price")[product.id], 80.0
        )
        planned = product.with_context(**{costs_key: {product.id: 90.0}})
        self.assertAlmostEqual(
            planned._price_compute("standard_price")[product.id], 90.0
        )
        self.assertAlmostEqual(
            planned._price_compute("standard_price", uom=self.uom_box)[product.id],
            1080.0,
        )
        self.assertAlmostEqual(
            planned._price_compute("list_price")[product.id],
            product._price_compute("list_price")[product.id],
        )
        other = product.with_context(**{costs_key: {self.product_basin.id: 1.0}})
        self.assertAlmostEqual(other._price_compute("standard_price")[product.id], 80.0)

    def test_sale_price_of_unchanged_products_is_not_computed_again(self):
        product = self._create_product(
            "Stable Price",
            cost=90.0,
            sellers=[self._seller(self.vendor_a, 100.0, discount=10.0)],
        )
        Pricelist = type(self.env["product.pricelist"])
        get_products_price = Pricelist._get_products_price
        planned = []

        def get_and_record(pricelist, products, *args, **kwargs):
            if products.env.context.get(PREVIEW_COSTS_KEY):
                planned.extend(products.ids)
            return get_products_price(pricelist, products, *args, **kwargs)

        with patch.object(Pricelist, "_get_products_price", get_and_record):
            wizard = self._preview(
                product | self.product_mixer, pricelist_id=self.pricelist_main.id
            )
        # Only the product whose cost changes is priced with its new cost.
        self.assertEqual(planned, self.product_mixer.ids)
        line = self._line(wizard, product)
        self.assertEqual(line.state, "unchanged")
        self.assertAlmostEqual(line.current_sale_price, 157.5)
        self.assertAlmostEqual(line.new_sale_price, line.current_sale_price)
        self.assertAlmostEqual(line.sale_change_pct, 0.0)
        self.assertAlmostEqual(
            self._line(wizard, self.product_mixer).new_sale_price, 157.5
        )

    def test_cost_history(self):
        if not self._has_stock_account():
            self.skipTest("stock_account is not installed")
        history = self._cost_history_count(self.product_mixer)
        self._apply(self.product_mixer)
        self.assertEqual(self._cost_history_count(self.product_mixer), history + 1)
        value = self._cost_history(self.product_mixer)[:1]
        self.assertAlmostEqual(value.value, 90.0)
        self.assertEqual(value.company_id, self.company)

    def test_invalid_quantity(self):
        with self.assertRaises(UserError):
            self._preview(self.product_mixer, quantity=0.0)

    def test_purchase_manager_is_denied(self):
        # sudo: only an administrator creates users.
        buyer = new_test_user(
            self.env(su=True),
            login="pcfs_buyer",
            groups="base.group_user,purchase.group_purchase_manager",
        )
        wizard_model = self.Wizard.with_user(buyer).with_context(
            active_model="product.product", active_ids=self.product_mixer.ids
        )
        with self.assertRaises(AccessError):
            wizard_model.default_get(["product_ids"])

    def test_product_manager_can_apply(self):
        # A product manager without any purchase group.
        manager = new_test_user(
            self.env(su=True),
            login="pcfs_manager",
            groups="base.group_user,product.group_product_manager",
        )
        wizard = (
            self.Wizard.with_user(manager)
            .with_context(
                active_model="product.supplierinfo", active_ids=self.row_mixer_a.ids
            )
            .create({"pricelist_id": self.pricelist_main.id})
        )
        wizard.action_preview()
        line = self._line(wizard, self.product_mixer)
        self.assertAlmostEqual(line.new_sale_price, 157.5)
        wizard.action_apply()
        self.assertAlmostEqual(self._cost(self.product_mixer), 90.0)
        self.assertEqual(wizard.batch_id.user_id, manager)
