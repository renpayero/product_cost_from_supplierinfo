# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import CostFromSupplierinfoCommon


@tagged("post_install", "-at_install")
class TestCostBatch(CostFromSupplierinfoCommon):
    def _assert_revert_notification(self, action, reverted, left):
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["type"], "success" if reverted else "warning")
        self.assertEqual(
            action["params"]["message"],
            f"Reverted products: {reverted}. Products left as they are: {left}.",
        )
        self.assertEqual(
            action["params"]["next"], {"type": "ir.actions.act_window_close"}
        )

    def test_batch_values(self):
        batch = self._apply(
            self.row_mixer_a | self.row_shower, pricelist_id=self.pricelist_main.id
        )
        self.assertRecordValues(
            batch,
            [
                {
                    "name": "Vendor A · Products: 3",
                    "company_id": self.company.id,
                    "user_id": self.env.user.id,
                    "source": "supplierinfo",
                    "pricelist_id": self.pricelist_main.id,
                    "state": "done",
                    "count_updated": 3,
                    "count_unchanged": 0,
                    "count_skipped": 0,
                }
            ],
        )
        self.assertEqual(
            batch.line_ids.product_id,
            self.product_mixer | self.shower_chrome | self.shower_black,
        )
        self.assertEqual(
            batch.line_ids.supplierinfo_id, self.row_mixer_a | self.row_shower
        )

    def test_name_with_several_vendors(self):
        wizard = self._preview(self.row_mixer_a | self.row_shower_black)
        # Vendor B comes second for the black variant: selected by hand.
        wizard.action_select_all()
        wizard.action_apply()
        self.assertEqual(wizard.batch_id.name, "Several vendors · Products: 2")

    def test_history_is_read_only(self):
        # Only the module writes the history, in sudo: a product manager can
        # read it and revert it, not change it.
        batch = self._apply(self.row_mixer_a)
        self.assertEqual(batch.line_ids.new_cost, 90.0)
        with self.assertRaises(AccessError):
            batch.write({"state": "reverted"})
        with self.assertRaises(AccessError):
            batch.line_ids.write({"old_cost": 1.0})
        with self.assertRaises(AccessError):
            self.Batch.create({"company_id": self.company.id})
        self.assertEqual(batch.state, "done")

    def test_revert(self):
        batch = self._apply(self.row_mixer_a | self.row_shower)
        history = self._has_stock_account() and self._cost_history_count(
            self.product_mixer
        )
        action = batch.action_revert()
        self._assert_revert_notification(action, reverted=3, left=0)
        self.assertEqual(batch.state, "reverted")
        self.assertTrue(all(batch.line_ids.mapped("reverted")))
        self.assertAlmostEqual(self._cost(self.product_mixer), 80.0)
        self.assertAlmostEqual(self._cost(self.shower_chrome), 40.0)
        self.assertAlmostEqual(self._cost(self.shower_black), 40.0)
        self.assertEqual(batch.revert_user_id, self.env.user)
        self.assertTrue(batch.revert_date)
        if self._has_stock_account():
            # Odoo records the revert in the cost history too.
            self.assertEqual(
                self._cost_history_count(self.product_mixer), history + 1
            )

    def test_revert_skips_a_modified_cost(self):
        batch = self._apply(self.row_mixer_a | self.row_shower)
        self.shower_chrome.standard_price = 55.0
        action = batch.action_revert()
        self._assert_revert_notification(action, reverted=2, left=1)
        self.assertEqual(batch.state, "partial")
        chrome_line = batch.line_ids.filtered(
            lambda line: line.product_id == self.shower_chrome
        )
        self.assertRecordValues(
            chrome_line,
            [{"reverted": False, "revert_note": "Cost modified after this change"}],
        )
        self.assertAlmostEqual(self._cost(self.shower_chrome), 55.0)
        self.assertAlmostEqual(self._cost(self.shower_black), 40.0)
        self.assertAlmostEqual(self._cost(self.product_mixer), 80.0)
        # Once its cost is back to the one of the update, it can be reverted.
        self.shower_chrome.standard_price = 50.0
        action = batch.action_revert()
        self._assert_revert_notification(action, reverted=1, left=0)
        self.assertEqual(batch.state, "reverted")
        self.assertRecordValues(chrome_line, [{"reverted": True, "revert_note": False}])
        self.assertAlmostEqual(self._cost(self.shower_chrome), 40.0)

    def test_nothing_to_revert_keeps_the_state(self):
        batch = self._apply(self.row_mixer_a)
        self.product_mixer.standard_price = 95.0
        action = batch.action_revert()
        self._assert_revert_notification(action, reverted=0, left=1)
        self.assertRecordValues(
            batch, [{"state": "done", "revert_user_id": False, "revert_date": False}]
        )
        self.assertEqual(batch.line_ids.revert_note, "Cost modified after this change")
        self.assertAlmostEqual(self._cost(self.product_mixer), 95.0)

    def test_revert_skips_a_cost_changed_by_a_later_update(self):
        # 80 -> 90, 90 -> 80 and 80 -> 90: the cost is again the one of the
        # first update, but the last update wrote it.
        first = self._apply(self.row_mixer_a)
        self.row_mixer_a.discount = 20.0
        second = self._apply(self.row_mixer_a)
        self.row_mixer_a.discount = 10.0
        third = self._apply(self.row_mixer_a)
        self.assertEqual(
            [batch.line_ids.new_cost for batch in (first, second, third)],
            [90.0, 80.0, 90.0],
        )
        action = first.action_revert()
        self._assert_revert_notification(action, reverted=0, left=1)
        self.assertAlmostEqual(self._cost(self.product_mixer), 90.0)
        self.assertRecordValues(
            first.line_ids,
            [{"reverted": False, "revert_note": "Changed by a later cost update"}],
        )
        self.assertEqual(first.state, "done")
        # Reverted from the last one, every update is undone in turn.
        for batch, cost in ((third, 80.0), (second, 90.0), (first, 80.0)):
            with self.subTest(batch=batch.id):
                self._assert_revert_notification(
                    batch.action_revert(), reverted=1, left=0
                )
                self.assertEqual(batch.state, "reverted")
                self.assertAlmostEqual(self._cost(self.product_mixer), cost)

    def test_revert_skips_a_cost_computed_by_odoo(self):
        if not self._has_stock_account():
            self.skipTest("stock_account is not installed")
        batch = self._apply(self.row_mixer_a)
        # Odoo computes the cost of the mixer from now on.
        fifo = self.env["product.category"].create(
            {"name": "FIFO", "property_cost_method": "fifo"}
        )
        self.product_mixer.categ_id = fifo
        cost = self._cost(self.product_mixer)
        with self._capture_cost_writes() as written:
            action = batch.action_revert()
        self.assertFalse(written)
        self._assert_revert_notification(action, reverted=0, left=1)
        self.assertAlmostEqual(self._cost(self.product_mixer), cost)
        self.assertRecordValues(
            batch.line_ids,
            [{"reverted": False, "revert_note": "Cost method is FIFO/AVCO"}],
        )

    def test_second_revert_does_nothing(self):
        batch = self._apply(self.row_mixer_a)
        batch.action_revert()
        revert_date = batch.revert_date
        with self._capture_cost_writes() as written:
            action = batch.action_revert()
        self.assertFalse(written)
        self._assert_revert_notification(action, reverted=0, left=0)
        self.assertEqual(batch.state, "reverted")
        self.assertEqual(batch.revert_date, revert_date)
        self.assertAlmostEqual(self._cost(self.product_mixer), 80.0)

    def test_revert_needs_product_rights(self):
        batch = self._apply(self.row_mixer_a)
        # The cost changed after the update: reverting writes no cost, only the
        # note of the line, so only the check at the start can refuse it.
        self.product_mixer.standard_price = 95.0
        # With the standard groups, only product managers (administrators are
        # product managers too) can read the cost updates. This user reads them
        # through an access right of his own, but cannot write products.
        # sudo: only an administrator sets up groups, access rights and users.
        admin_env = self.env(su=True)
        readers = admin_env["res.groups"].create({"name": "Cost update readers"})
        admin_env["ir.model.access"].create(
            [
                {
                    "name": f"{model} readers",
                    "model_id": admin_env["ir.model"]._get_id(model),
                    "group_id": readers.id,
                    "perm_read": True,
                }
                for model in (
                    "product.cost.from.supplierinfo.batch",
                    "product.cost.from.supplierinfo.batch.line",
                )
            ]
        )
        viewer = new_test_user(
            admin_env,
            login="pcfs_viewer",
            group_ids=[self.env.ref("base.group_user").id, readers.id],
        )
        self.assertEqual(batch.with_user(viewer).line_ids.new_cost, 90.0)
        with self.assertRaises(AccessError):
            batch.with_user(viewer).action_revert()
        self.assertFalse(batch.line_ids.revert_note)
        self.assertAlmostEqual(self._cost(self.product_mixer), 95.0)

    def test_multicompany(self):
        product = self._create_product("Shared Valve", cost=10.0)
        row = self._create_row(product, self.vendor_a, 30.0, company_id=False)
        product.with_company(self.company_b).standard_price = 20.0
        batch_b = self._apply(row, company_id=self.company_b.id, threshold=100.0)
        batch_a = self._apply(self.row_mixer_a)
        self.assertEqual(batch_b.company_id, self.company_b)
        # sudo: only an administrator creates users.
        manager = new_test_user(
            self.env(su=True),
            login="pcfs_manager_a",
            groups="base.group_user,product.group_product_manager",
            company_id=self.company.id,
        )
        visible = self.Batch.with_user(manager).search([])
        self.assertIn(batch_a, visible)
        self.assertNotIn(batch_b, visible)
        lines_b = (
            self.env["product.cost.from.supplierinfo.batch.line"]
            .with_user(manager)
            .search([("batch_id", "=", batch_b.id)])
        )
        self.assertFalse(lines_b)
        batch_b.action_revert()
        self.assertAlmostEqual(self._cost(product, self.company_b), 20.0)
        self.assertAlmostEqual(self._cost(product), 10.0)
        self.assertEqual(batch_a.state, "done")
