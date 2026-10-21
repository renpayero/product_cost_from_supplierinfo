# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import unittest
from datetime import datetime
from unittest.mock import patch

import psycopg2.errors

from odoo import Command
from odoo.tests import tagged

from ..models.product_product import POS_REFRESH_KEY, POS_REFRESH_RETRIES
from .common import CostFromSupplierinfoCommon

OLD_DATE = datetime(2000, 1, 1)
LOGGER = "odoo.addons.product_cost_from_supplierinfo.models.product_product"


def _forbidden_write(records, vals):
    raise AssertionError("pos.config.write() must not be called")


@tagged("post_install", "-at_install")
class TestCostPos(CostFromSupplierinfoCommon):
    """Point of sale refresh. Skipped when point_of_sale is not installed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if "pos.config" not in cls.env:
            raise unittest.SkipTest("point_of_sale is not installed")
        Pricelist = cls.env["product.pricelist"]
        # A pricelist that does not depend on the cost.
        cls.pricelist_list = Pricelist.create(
            {
                "name": "List",
                "item_ids": [
                    Command.create(
                        {
                            "applied_on": "3_global",
                            "compute_price": "percentage",
                            "base": "list_price",
                            "percent_price": 10.0,
                        }
                    )
                ],
            }
        )
        # The pricelists of the fixtures belong to the main company: a point of
        # sale of company B needs a pricelist of its own.
        cls.pricelist_main_b = Pricelist.with_company(cls.company_b).create(
            {
                "name": "Main B",
                "company_id": cls.company_b.id,
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
        # sudo: only a point of sale administrator creates the points of sale.
        Config = cls.env["pos.config"].sudo()
        # No payment methods: the default ones need a bank journal, and no
        # session is opened in these tests.
        values = {"payment_method_ids": [Command.clear()]}

        def using(*pricelists):
            return {
                "use_pricelist": True,
                "pricelist_id": pricelists[0].id,
                "available_pricelist_ids": [Command.set([pl.id for pl in pricelists])],
            }

        # Test Shop applies Main, which is based on the cost, and Cash Shop
        # applies Cash, which is based on Main. List Shop only applies a
        # pricelist that does not depend on the cost, and the shop without
        # pricelists sells at the sales price: the till ignores its default
        # pricelist.
        cls.config = Config.create(
            dict(values, name="Test Shop", **using(cls.pricelist_main))
        )
        cls.config_cash = Config.create(
            dict(
                values,
                name="Cash Shop",
                **using(cls.pricelist_list, cls.pricelist_cash),
            )
        )
        cls.config_list = Config.create(
            dict(values, name="List Shop", **using(cls.pricelist_list))
        )
        cls.config_no_pricelist = Config.create(
            dict(
                values,
                name="Shop without pricelists",
                pricelist_id=cls.pricelist_main.id,
            )
        )
        # An archived point of sale keeps its data in the browser, and uses
        # it again if it is restored.
        cls.config_archived = Config.create(
            dict(
                values,
                name="Archived Shop",
                active=False,
                **using(cls.pricelist_main),
            )
        )
        # A point of sale of another company, which the updates of the main
        # company must not touch. Odoo creates its warehouse and its journal
        # (tests create a warehouse for every new company); the chart of
        # accounts is only needed to open a session.
        cls.config_b = Config.with_company(cls.company_b).create(
            dict(values, name="Shop B", **using(cls.pricelist_main_b))
        )
        cls.configs = (
            cls.config
            | cls.config_cash
            | cls.config_list
            | cls.config_no_pricelist
            | cls.config_archived
            | cls.config_b
        )
        # The points of sale of the main company whose prices depend on the
        # cost.
        cls.refreshed = cls.config | cls.config_cash | cls.config_archived
        cls.product_mixer.available_in_pos = True

    def setUp(self):
        super().setUp()
        # Start without the post-commit callbacks of the fixtures: another
        # module may refresh the points of sale after any change of rules.
        self.env.cr.postcommit.clear()
        self._age(self.configs)

    def _age(self, configs):
        """Give ``configs`` an old data date, to see it move."""
        self.env.flush_all()
        configs._write({"last_data_change": OLD_DATE})
        configs.invalidate_recordset(["last_data_change"])

    def _refreshed(self):
        """Return the configurations of the tests whose data date moved."""
        self.env.invalidate_all()
        return self.configs.filtered(
            lambda config: config.last_data_change > OLD_DATE
        )

    def _run_postcommit(self):
        # As after a real commit: the callbacks open their own cursor, which
        # the registry test mode points to the cursor of the test.
        with self.enter_registry_test_mode():
            self.env.cr.postcommit.run()

    def _refresh_callbacks(self):
        return [
            func
            for func in self.env.cr.postcommit._funcs
            if func.__name__ == "_cost_from_supplierinfo_refresh_pos"
        ]

    # Which points of sale

    def test_points_of_sale_whose_prices_depend_on_the_cost(self):
        Product = self.env["product.product"]
        self.assertEqual(
            Product._cost_from_supplierinfo_pos_configs(self.company) & self.configs,
            self.refreshed,
        )
        self.assertEqual(
            Product._cost_from_supplierinfo_pos_configs(self.company_b)
            & self.configs,
            self.config_b,
        )
        # Once it uses pricelists, the till applies its default pricelist.
        self.config_no_pricelist.write(
            {
                "use_pricelist": True,
                "available_pricelist_ids": [Command.set(self.pricelist_main.ids)],
            }
        )
        self.assertIn(
            self.config_no_pricelist,
            Product._cost_from_supplierinfo_pos_configs(self.company),
        )

    def test_point_of_sale_using_the_cost_through_a_preset(self):
        Config = self.env["pos.config"].sudo()
        if "available_preset_ids" not in Config._fields:
            self.skipTest("This version of the point of sale has no presets.")
        preset = (
            self.env["pos.preset"]
            .sudo()
            .create({"name": "Take away", "pricelist_id": self.pricelist_main.id})
        )
        values = {
            "name": "Preset Shop",
            "pricelist_id": self.pricelist_list.id,
            "default_preset_id": preset.id,
            "available_preset_ids": [Command.set(preset.ids)],
            "payment_method_ids": [Command.clear()],
        }
        config = Config.create(dict(values, use_presets=True))
        # Without "use presets", the till ignores the pricelists of presets.
        without_presets = Config.create(dict(values, name="Shop without presets"))
        configs = self.env["product.product"]._cost_from_supplierinfo_pos_configs(
            self.company
        )
        self.assertIn(config, configs)
        self.assertNotIn(without_presets, configs)

    def test_no_refresh_without_a_pricelist_based_on_the_cost(self):
        # sudo: a sales administrator changes the rules.
        self.pricelist_main.item_ids.sudo().write({"base": "list_price"})
        # Only the refresh of the cost update is looked at, not one that
        # another module may schedule for this change of rules.
        self.env.cr.postcommit.clear()
        self.assertFalse(
            self.env["product.product"]._cost_from_supplierinfo_pos_configs(
                self.company
            )
            & self.configs
        )
        self._apply(self.row_mixer_a)
        self._run_postcommit()
        self.assertFalse(self._refreshed())

    # The refresh

    def test_refresh_after_commit(self):
        self.assertEqual(self.config_b.company_id, self.company_b)
        self._apply(self.row_mixer_a)
        # Nothing moves inside the transaction.
        self.assertEqual(self.config.last_data_change, OLD_DATE)
        self.assertEqual(len(self._refresh_callbacks()), 1)
        self._run_postcommit()
        # Only the points of sale of the company of the update whose prices
        # depend on the cost reload.
        self.assertEqual(self._refreshed(), self.refreshed)

    def test_no_refresh_without_pos_product(self):
        self._apply(self.row_basin, threshold=50.0)
        self.assertNotIn(POS_REFRESH_KEY, self.env.cr.postcommit.data)
        self.assertFalse(self._refresh_callbacks())
        self._run_postcommit()
        self.assertFalse(self._refreshed())

    def test_refresh_does_not_write_the_config(self):
        self._apply(self.row_mixer_a)
        with patch.object(type(self.env["pos.config"]), "write", _forbidden_write):
            self._run_postcommit()
        self.assertEqual(self._refreshed(), self.refreshed)

    def test_refresh_now(self):
        with patch.object(type(self.env["pos.config"]), "write", _forbidden_write):
            self.env["product.product"]._cost_from_supplierinfo_pos_refresh_now(
                self.config
            )
            self.env.flush_all()
        self.assertGreater(self.config.last_data_change, OLD_DATE)

    def test_refresh_is_tried_again_after_a_concurrent_update(self):
        self._apply(self.row_mixer_a)
        Product = self.env.registry["product.product"]
        original = Product._cost_from_supplierinfo_pos_refresh_now
        calls = []

        def refresh_now(model, configs):
            calls.append(configs)
            if len(calls) < 3:
                raise psycopg2.errors.SerializationFailure("concurrent update")
            return original(model, configs)

        with patch.object(
            Product, "_cost_from_supplierinfo_pos_refresh_now", refresh_now
        ):
            self._run_postcommit()
        self.assertEqual(len(calls), 3)
        self.assertEqual(self._refreshed(), self.refreshed)

    def test_refresh_gives_up_after_the_retries(self):
        self._apply(self.row_mixer_a)
        error = psycopg2.errors.SerializationFailure("concurrent update")
        with (
            patch.object(
                self.env.registry["product.product"],
                "_cost_from_supplierinfo_pos_refresh_now",
                side_effect=error,
            ) as refresh_now,
            self.assertLogs(LOGGER, "ERROR") as logs,
        ):
            self._run_postcommit()
        self.assertEqual(refresh_now.call_count, POS_REFRESH_RETRIES + 1)
        self.assertEqual(len(logs.records), 1)
        self.assertFalse(self._refreshed())

    def test_one_callback_per_transaction(self):
        self._apply(self.row_mixer_a)
        self.product_mixer._cost_from_supplierinfo_schedule_pos_refresh(self.company)
        self.assertEqual(len(self._refresh_callbacks()), 1)
        self.assertEqual(
            self.env.cr.postcommit.data[POS_REFRESH_KEY], {self.company.id}
        )

    def test_revert_refreshes(self):
        batch = self._apply(self.row_mixer_a)
        self._run_postcommit()
        self._age(self.configs)
        batch.action_revert()
        self.assertEqual(len(self._refresh_callbacks()), 1)
        self._run_postcommit()
        self.assertEqual(self._refreshed(), self.refreshed)

    def test_open_session_warning(self):
        def _open_session(configs):
            for config in configs:
                config.has_active_session = config in self.configs
                config.current_session_id = False
                config.current_session_state = False
                config.number_of_rescue_session = 0

        Config = type(self.env["pos.config"])
        with patch.object(Config, "_compute_current_session", _open_session):
            self.env.invalidate_all()
            wizard = self._preview(self.row_mixer_a)
            self.assertIn("Test Shop", wizard.pos_warning)
            self.assertIn("Cash Shop", wizard.pos_warning)
            # Reopening deletes the orders not sent yet: the warning says so.
            self.assertIn(
                "deletes, in that browser, every order not yet sent to the server",
                wizard.pos_warning,
            )
            self.assertIn("does not reload anything", wizard.pos_warning)
            # Not concerned: a point of sale whose prices do not depend on the
            # cost, an archived one and the open session of another company.
            for name in ("List Shop", "without pricelists", "Archived", "Shop B"):
                self.assertNotIn(name, wizard.pos_warning)
            # No warning when no product of the update is sold there.
            self.assertFalse(self._preview(self.row_basin).pos_warning)
        self.env.invalidate_all()
