# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import Form, tagged
from odoo.tests.common import new_test_user
from odoo.tools import format_list, formatLang

from .common import CostFromSupplierinfoCommon

WIZARD_MODULE = (
    "odoo.addons.product_cost_from_supplierinfo.wizards."
    "product_cost_from_supplierinfo_wizard"
)
BATCH_URL = (
    "/odoo/action-product_cost_from_supplierinfo."
    "product_cost_from_supplierinfo_batch_action/%s"
)


@tagged("post_install", "-at_install")
class TestCostFromRows(CostFromSupplierinfoCommon):
    def test_defaults_from_rows(self):
        rows = self.row_mixer_a | self.row_basin
        wizard = self._wizard(rows)
        self.assertEqual(wizard.source, "supplierinfo")
        self.assertEqual(wizard.supplierinfo_ids, rows)
        self.assertEqual(wizard.selection_summary, "Vendor prices selected: 2")
        self.assertFalse(wizard.selection_truncated)
        self.assertEqual(wizard.company_id, self.company)
        self.assertAlmostEqual(wizard.threshold, 30.0)

    def test_opened_like_the_web_client(self):
        # The web client asks for the default values of the fields of the
        # form, which does not show the vendor prices: they are set when the
        # wizard is saved, from the context of the action.
        context = {
            "active_model": "product.supplierinfo",
            "active_id": self.row_mixer_a.id,
            "active_ids": self.row_mixer_a.ids,
        }
        with Form(self.Wizard.with_context(**context)) as wizard_form:
            self.assertEqual(wizard_form.selection_summary, "Vendor prices selected: 1")
            wizard_form.pricelist_id = self.pricelist_main
        wizard = wizard_form.record
        self.assertEqual(wizard.source, "supplierinfo")
        self.assertEqual(wizard.supplierinfo_ids, self.row_mixer_a)
        wizard.action_preview()
        line = self._line(wizard, self.product_mixer)
        self.assertRecordValues(line, [{"state": "update", "apply": True}])
        self.assertAlmostEqual(line.new_sale_price, 157.5)
        wizard.action_apply()
        self.assertAlmostEqual(self._cost(self.product_mixer), 90.0)
        self.assertEqual(wizard.batch_id.user_id, self.manager)

    def test_previews_are_private(self):
        wizard = self._preview(self.row_mixer_a)
        Line = self.env["product.cost.from.supplierinfo.wizard.line"]
        # sudo: only an administrator creates users.
        other = new_test_user(
            self.env(su=True),
            login="pcfs_other_manager",
            groups="base.group_user,product.group_product_manager",
        )
        self.assertEqual(self.Wizard.search([("id", "=", wizard.id)]), wizard)
        self.assertEqual(Line.search([("wizard_id", "=", wizard.id)]), wizard.line_ids)
        # Another product manager does not see the costs of this preview.
        self.assertFalse(
            self.Wizard.with_user(other).search([("id", "=", wizard.id)])
        )
        self.assertFalse(
            Line.with_user(other).search([("wizard_id", "=", wizard.id)])
        )

    def test_selection_truncated(self):
        rows = self.row_mixer_a | self.row_basin
        # sudo: only an administrator changes the system parameters.
        self.env["ir.config_parameter"].sudo().set_param("web.active_ids_limit", 2)
        self.assertTrue(self._wizard(rows).selection_truncated)
        self.assertFalse(self._wizard(self.row_mixer_a).selection_truncated)

    def test_cost_and_apply(self):
        wizard = self._preview(self.row_mixer_a)
        self.assertEqual(wizard.state, "preview")
        self.assertRecordValues(
            self._line(wizard, self.product_mixer),
            [
                {
                    "state": "update",
                    "apply": True,
                    "flagged": False,
                    "partner_id": self.vendor_a.id,
                    "supplierinfo_id": self.row_mixer_a.id,
                    "vendor_price": 100.0,
                    "discount": 10.0,
                    "current_cost": 80.0,
                    "new_cost": 90.0,
                    "change_pct": 12.5,
                    "message": False,
                }
            ],
        )
        action = wizard.action_apply()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(
            action["params"]["next"], {"type": "ir.actions.act_window_close"}
        )
        # The message ends with a link to the cost update.
        batch = wizard.batch_id
        self.assertEqual(action["params"]["message"], "Updated costs: 1. %s")
        self.assertEqual(
            action["params"]["links"],
            [{"label": batch.name, "url": BATCH_URL % batch.id}],
        )
        self.assertAlmostEqual(self._cost(self.product_mixer), 90.0)
        self.assertRecordValues(
            batch.line_ids,
            [
                {
                    "product_id": self.product_mixer.id,
                    "partner_id": self.vendor_a.id,
                    "old_cost": 80.0,
                    "new_cost": 90.0,
                    "reverted": False,
                }
            ],
        )

    def test_apply_twice_in_the_same_window(self):
        # A second click, for instance after the browser gave up waiting for
        # the answer to the first one.
        wizard = self._preview(self.row_mixer_a)
        wizard.action_apply()
        batch = wizard.batch_id
        line = self._line(wizard, self.product_mixer)
        with self._capture_cost_writes() as written:
            action = wizard.action_apply()
        self.assertFalse(written)
        self.assertEqual(action["params"]["title"], "Already applied")
        self.assertEqual(
            action["params"]["message"],
            "The costs of this preview were already applied: %s",
        )
        self.assertEqual(
            action["params"]["links"],
            [{"label": batch.name, "url": BATCH_URL % batch.id}],
        )
        self.assertEqual(
            action["params"]["next"], {"type": "ir.actions.act_window_close"}
        )
        self.assertEqual(wizard.batch_id, batch)
        self.assertEqual(self.Batch.search_count([("id", ">", batch.id)]), 0)
        self.assertRecordValues(
            line, [{"state": "update", "apply": True, "message": False}]
        )
        # Back to the configuration: a new preview can be applied again.
        wizard.action_back()
        self.assertFalse(wizard.batch_id)

    def test_lines_already_applied(self):
        # Two windows with the same mixer: the second one finds its new cost
        # already written by the first one.
        first = self._preview(self.row_mixer_a)
        second = self._preview(self.row_mixer_a | self.row_basin, threshold=50.0)
        alone = self._preview(self.row_mixer_a)
        first.action_apply()
        with self._capture_cost_writes() as written:
            action = second.action_apply()
        self.assertEqual(written, self.product_basin.ids)
        self.assertEqual(
            action["params"]["message"],
            "Updated costs: 1. Already had the new cost: 1. %s",
        )
        self.assertRecordValues(
            self._line(second, self.product_mixer),
            [{"state": "update", "apply": True, "message": False}],
        )
        self.assertEqual(second.batch_id.line_ids.product_id, self.product_basin)
        # Nothing left to write: no cost update is recorded.
        action = alone.action_apply()
        self.assertEqual(action["params"]["title"], "Nothing was applied")
        self.assertEqual(
            action["params"]["message"],
            "The selected products already had the new cost.",
        )
        self.assertEqual(
            action["params"]["next"], {"type": "ir.actions.act_window_close"}
        )
        self.assertFalse(alone.batch_id)

    def test_cost_in_another_company(self):
        product = self._create_product("Shared Valve", cost=10.0)
        row = self._create_row(product, self.vendor_a, 30.0, company_id=False)
        product.with_company(self.company_b).standard_price = 20.0
        wizard = self._preview(row, company_id=self.company_b.id, threshold=100.0)
        line = self._line(wizard, product)
        self.assertEqual(line.state, "update")
        self.assertAlmostEqual(line.current_cost, 20.0)
        wizard.action_apply()
        self.assertAlmostEqual(self._cost(product, self.company_b), 30.0)
        self.assertAlmostEqual(self._cost(product), 10.0)
        self.assertEqual(wizard.batch_id.company_id, self.company_b)

    def test_two_rows_for_the_same_variant(self):
        row = self._create_row(self.product_mixer, self.vendor_b, 70.0)
        wizard = self._preview(self.row_mixer_a | row)
        lines = self._line(wizard, self.product_mixer)
        self.assertEqual(lines.mapped("state"), ["skip", "skip"])
        self.assertEqual(
            set(lines.mapped("message")),
            {"Vendor prices selected for this product: 2"},
        )
        self.assertFalse(any(lines.mapped("apply")))

    def test_row_of_the_main_vendor(self):
        line = self._line(self._preview(self.row_mixer_a), self.product_mixer)
        self.assertRecordValues(
            line, [{"flagged": False, "apply": True, "message": False}]
        )

    def test_row_of_another_vendor(self):
        # Vendor B is the second vendor of the mixer: its price is not used for
        # the cost without a check.
        line = self._line(self._preview(self.row_mixer_b), self.product_mixer)
        self.assertRecordValues(
            line,
            [
                {
                    "state": "update",
                    "new_cost": 95.0,
                    "flagged": True,
                    "apply": False,
                    "warning_level": "2",
                    "message": "The main vendor of this product is Vendor A.",
                }
            ],
        )

    def test_vendors_sharing_the_first_position(self):
        product = self._create_product(
            "Siphon",
            cost=50.0,
            sellers=[
                {"partner_id": self.vendor_a.id, "price": 55.0},
                {"partner_id": self.vendor_b.id, "price": 52.0},
            ],
        )
        # The price of vendor A, with the same sequence as vendor B.
        line = self._line(self._preview(self._row(product, self.vendor_a)), product)
        self.assertRecordValues(
            line,
            [
                {
                    "state": "update",
                    "flagged": True,
                    "apply": False,
                    "warning_level": "2",
                }
            ],
        )
        # In the order of Odoo: the lower price first.
        self.assertEqual(
            line.message,
            "Several vendors share the first position (%s): the vendor was chosen "
            "by list order. Set the order of the vendors of the product."
            % format_list(self.env, ["Vendor B", "Vendor A"]),
        )

    def test_template_row_and_variant_row(self):
        wizard = self._preview(self.row_shower | self.row_shower_black)
        chrome = self._line(wizard, self.shower_chrome)
        black = self._line(wizard, self.shower_black)
        self.assertEqual(chrome.state, "update")
        self.assertAlmostEqual(chrome.new_cost, 50.0)
        self.assertEqual(black.mapped("state"), ["skip", "skip"])

    def test_template_row_applies_to_all_variants(self):
        wizard = self._preview(self.row_shower)
        self.assertEqual(
            wizard.line_ids.product_id, self.shower_chrome | self.shower_black
        )
        self.assertEqual(set(wizard.line_ids.mapped("new_cost")), {50.0})

    def test_variant_row_applies_to_its_variant_only(self):
        wizard = self._preview(self.row_shower_black)
        self.assertEqual(wizard.line_ids.product_id, self.shower_black)
        # Vendor B comes second for the black variant: selected by hand.
        self.assertTrue(wizard.line_ids.flagged)
        wizard.action_select_all()
        wizard.action_apply()
        self.assertAlmostEqual(self._cost(self.shower_black), 45.0)
        self.assertAlmostEqual(self._cost(self.shower_chrome), 40.0)

    def test_skip_reasons(self):
        cases = []

        def add_case(message, name, price=10.0, product_values=None, **row_values):
            product = self._create_product(name, **(product_values or {}))
            row = self._create_row(product, self.vendor_a, price, **row_values)
            cases.append((row, product, message))
            return row, product

        row, _product = add_case("Archived vendor", "Old Vendor Item")
        row.partner_id = self.vendor_c
        self.vendor_c.action_archive()
        add_case(
            "Vendor price of another company",
            "Company B Price",
            company_id=self.company_b.id,
        )
        add_case("Vendor price is zero", "Free Sample", price=0.0)
        _row, product = add_case("Archived product", "Old Model")
        product.action_archive()
        add_case(
            "Product of another company",
            "Company B Product",
            product_values={"company_id": self.company_b.id},
            company_id=False,
        )
        uom_litre = self.env["uom.uom"].create(
            {"name": "Test Litre", "relative_factor": 1.0}
        )
        add_case(
            "Incompatible units of measure", "Bulk Product", product_uom_id=uom_litre.id
        )
        add_case("The cost would be negative", "Overpriced Promo", discount=150.0)
        rows = self.env["product.supplierinfo"].union(*(case[0] for case in cases))
        # With both companies enabled in the company switcher, the only way to
        # see the vendor price and the product of company B in the lists.
        wizard = self._preview(rows, companies=self.company | self.company_b)
        for _row, product, message in cases:
            with self.subTest(message=message):
                self.assertRecordValues(
                    self._line(wizard, product),
                    [{"state": "skip", "apply": False, "message": message}],
                )
        self.assertEqual(wizard.count_skip, len(cases))

    def test_currency_without_rate_is_skipped(self):
        # sudo: only an administrator sets up the currencies and their rates.
        currency = (
            self.env["res.currency"]
            .sudo()
            .with_context(active_test=False)
            .search([("name", "=", "CHF")], limit=1)
        )
        currency.action_unarchive()
        currency.rate_ids.unlink()
        product = self._create_product("Swiss Valve")
        row = self._create_row(product, self.vendor_a, 10.0, currency_id=currency.id)
        line = self._line(self._preview(row), product)
        self.assertEqual(line.message, "No exchange rate for CHF")

    def test_row_not_valid_today_is_flagged(self):
        expired = self._create_product("Expired Price")
        future = self._create_product("Future Price")
        rows = self._create_row(
            expired, self.vendor_a, 10.0, date_end="2020-01-31"
        ) | self._create_row(future, self.vendor_a, 10.0, date_start="2100-01-01")
        wizard = self._preview(rows)
        for product in expired | future:
            line = self._line(wizard, product)
            self.assertRecordValues(
                line,
                [
                    {
                        "state": "update",
                        "flagged": True,
                        "apply": False,
                        "warning_level": "2",
                    }
                ],
            )
            self.assertTrue(line.message.startswith("Vendor price not valid today ("))
        self.assertEqual(wizard.count_flagged, 2)

    def test_min_qty_info(self):
        product = self._create_product("Pallet Item", cost=8.0)
        row = self._create_row(product, self.vendor_a, 9.0, min_qty=10.0)
        box_row = self._create_row(
            self.product_basin,
            self.vendor_a,
            1500.0,
            min_qty=1.0,
            product_uom_id=self.uom_box.id,
        )
        # Of vendor A, the main vendor of the mixer: no other message.
        unit_row = self._create_row(
            self.product_mixer, self.vendor_a, 85.0, min_qty=1.0
        )
        wizard = self._preview(row | box_row | unit_row)
        line = self._line(wizard, product)
        self.assertRecordValues(
            line, [{"state": "update", "apply": True, "warning_level": "1"}]
        )
        self.assertTrue(line.message.startswith("Price for a minimum of 10"))
        # One box holds 12 units: a real minimum. One unit is no minimum.
        self.assertIn(
            "Price for a minimum of 1", self._line(wizard, self.product_basin).message
        )
        self.assertFalse(self._line(wizard, self.product_mixer).message)

    def test_unchanged_writes_nothing(self):
        product = self._create_product("Stable Price", cost=90.0)
        row = self._create_row(product, self.vendor_a, 100.0, discount=10.0)
        wizard = self._preview(row | self.row_mixer_a)
        line = self._line(wizard, product)
        self.assertRecordValues(line, [{"state": "unchanged", "apply": False}])
        history = self._has_stock_account() and self._cost_history_count(product)
        with self._capture_cost_writes() as written:
            wizard.action_apply()
        self.assertEqual(written, self.product_mixer.ids)
        self.assertAlmostEqual(self._cost(product), 90.0)
        if self._has_stock_account():
            self.assertEqual(self._cost_history_count(product), history)
        self.assertEqual(wizard.batch_id.count_unchanged, 1)

    def test_threshold(self):
        wizard = self._preview(self.row_basin)
        line = self._line(wizard, self.product_basin)
        self.assertAlmostEqual(line.change_pct, 35.0)
        self.assertRecordValues(
            line, [{"flagged": True, "apply": False, "warning_level": "2"}]
        )
        # The number is formatted like the active language does (35.00, 35,00).
        self.assertEqual(
            line.message, "Cost changes by %s %%" % formatLang(self.env, 35.0, digits=2)
        )
        wizard = self._preview(self.row_basin, threshold=50.0)
        line = self._line(wizard, self.product_basin)
        self.assertRecordValues(
            line, [{"flagged": False, "apply": True, "message": False}]
        )

    def test_no_current_cost(self):
        product = self._create_product("New Product", cost=0.0)
        row = self._create_row(product, self.vendor_a, 10.0)
        line = self._line(self._preview(row), product)
        self.assertRecordValues(
            line,
            [
                {
                    "state": "update",
                    "flagged": False,
                    "apply": True,
                    "message": "No current cost",
                }
            ],
        )

    def test_cost_changed_since_preview(self):
        wizard = self._preview(self.row_mixer_a | self.row_basin, threshold=50.0)
        self.product_mixer.standard_price = 85.0
        action = wizard.action_apply()
        self.assertAlmostEqual(self._cost(self.product_mixer), 85.0)
        self.assertAlmostEqual(self._cost(self.product_basin), 135.0)
        self.assertRecordValues(
            self._line(wizard, self.product_mixer),
            [
                {
                    "state": "skip",
                    "apply": False,
                    "message": "Cost changed since the preview",
                }
            ],
        )
        self.assertEqual(
            action["params"]["message"],
            "Updated costs: 1. "
            "Skipped because their cost changed since the preview: 1. %s",
        )
        self.assertEqual(wizard.batch_id.line_ids.product_id, self.product_basin)

    def test_cost_changed_for_every_line(self):
        wizard = self._preview(self.row_mixer_a)
        self.product_mixer.standard_price = 85.0
        action = wizard.action_apply()
        self.assertEqual(action["params"]["type"], "warning")
        self.assertEqual(action["params"]["next"]["res_id"], wizard.id)
        self.assertFalse(wizard.batch_id)
        self.assertAlmostEqual(self._cost(self.product_mixer), 85.0)

    def test_cost_method_changed_since_preview(self):
        if not self._has_stock_account():
            self.skipTest("stock_account is not installed")
        wizard = self._preview(self.row_mixer_a | self.row_basin, threshold=50.0)
        # Odoo computes the cost of the mixer from now on.
        fifo = self.env["product.category"].create(
            {"name": "FIFO", "property_cost_method": "fifo"}
        )
        self.product_mixer.categ_id = fifo
        cost = self._cost(self.product_mixer)
        with self._capture_cost_writes() as written:
            action = wizard.action_apply()
        self.assertEqual(written, self.product_basin.ids)
        self.assertAlmostEqual(self._cost(self.product_mixer), cost)
        self.assertRecordValues(
            self._line(wizard, self.product_mixer),
            [
                {
                    "state": "skip",
                    "apply": False,
                    "warning_level": "2",
                    "message": "Cost method is FIFO/AVCO",
                }
            ],
        )
        self.assertEqual(
            action["params"]["message"],
            "Updated costs: 1. Skipped because their cost method is FIFO/AVCO: 1. %s",
        )
        self.assertEqual(wizard.batch_id.line_ids.product_id, self.product_basin)

    def test_selection_buttons(self):
        wizard = self._preview(self.row_mixer_a | self.row_basin)
        mixer = self._line(wizard, self.product_mixer)
        basin = self._line(wizard, self.product_basin)
        self.assertEqual((mixer.apply, basin.apply), (True, False))
        wizard.action_select_all()
        self.assertEqual((mixer.apply, basin.apply), (True, True))
        wizard.action_unselect_flagged()
        self.assertEqual((mixer.apply, basin.apply), (True, False))
        wizard.action_select_none()
        self.assertEqual((mixer.apply, basin.apply), (False, False))
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_unselected_lines_are_not_applied(self):
        wizard = self._preview(self.row_mixer_a | self.row_basin)
        wizard.action_apply()
        self.assertAlmostEqual(self._cost(self.product_mixer), 90.0)
        self.assertAlmostEqual(self._cost(self.product_basin), 100.0)
        self.assertEqual(wizard.batch_id.count_skipped, 1)

    def test_back(self):
        wizard = self._preview(self.row_mixer_a)
        action = wizard.action_back()
        self.assertEqual(wizard.state, "config")
        self.assertFalse(wizard.line_ids)
        self.assertEqual(action["res_id"], wizard.id)
        wizard.action_preview()
        self.assertEqual(len(wizard.line_ids), 1)

    def test_apply_from_config_runs_preview(self):
        wizard = self._wizard(self.row_mixer_a)
        action = wizard.action_apply()
        self.assertEqual(wizard.state, "preview")
        self.assertEqual(action["res_id"], wizard.id)
        self.assertAlmostEqual(self._cost(self.product_mixer), 80.0)

    def test_empty_selection(self):
        wizard = self.Wizard.with_context(
            active_model="product.supplierinfo", active_ids=[]
        ).create({})
        with self.assertRaises(UserError):
            wizard.action_preview()

    def test_invalid_threshold(self):
        with self.assertRaises(UserError):
            self._preview(self.row_mixer_a, threshold=-1.0)

    def test_chunks_give_the_same_result(self):
        rows = self.row_mixer_a | self.row_shower
        fields_to_compare = ["product_id", "new_cost", "new_sale_price", "state"]
        wizard = self._preview(rows, pricelist_id=self.pricelist_main.id)
        expected = wizard.line_ids.read(fields_to_compare)
        with (
            patch(f"{WIZARD_MODULE}.PRICE_CHUNK_SIZE", 1),
            patch(f"{WIZARD_MODULE}.APPLY_CHUNK_SIZE", 1),
        ):
            wizard = self._preview(rows, pricelist_id=self.pricelist_main.id)
            result = wizard.line_ids.read(fields_to_compare)
            wizard.action_apply()
        for values in expected + result:
            values.pop("id")
        self.assertEqual(result, expected)
        self.assertEqual(len(wizard.batch_id.line_ids), 3)
        self.assertAlmostEqual(self._cost(self.shower_chrome), 50.0)
        self.assertAlmostEqual(self._cost(self.product_mixer), 90.0)
