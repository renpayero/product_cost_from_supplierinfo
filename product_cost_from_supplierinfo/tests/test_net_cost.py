# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import Command
from odoo.tests import Form, tagged
from odoo.tools import float_round

from .common import CostFromSupplierinfoCommon


@tagged("post_install", "-at_install")
class TestNetCost(CostFromSupplierinfoCommon):
    def _net_cost(self, price, taxes=None, partner=None, **row_values):
        product = self._create_product(
            "Net Cost Product",
            supplier_taxes_id=[Command.set(taxes.ids if taxes else [])],
        )
        row = self._create_row(product, partner or self.vendor_a, price, **row_values)
        return row._get_cost_from_supplierinfo(product, self.company, self.today)

    def _in_company_currency(self, amount):
        converted = self.currency_eur._convert(
            amount, self.company.currency_id, self.company, self.today, round=False
        )
        return float_round(converted, precision_digits=self.price_digits)

    def _mapping_vendor(self, name, tax, mapped_tax_values):
        """Return a vendor whose fiscal position replaces ``tax`` by a tax
        created with ``mapped_tax_values``."""
        # sudo: an accountant sets up the fiscal positions and the vendors.
        fiscal_position = (
            self.env["account.fiscal.position"]
            .sudo()
            .create({"name": f"Test {name}", "company_id": self.company.id})
        )
        self._create_tax(
            **mapped_tax_values,
            original_tax_ids=[Command.set(tax.ids)],
            fiscal_position_ids=[Command.set(fiscal_position.ids)],
        )
        return (
            self.env["res.partner"]
            .sudo()
            .create({"name": name, "property_account_position_id": fiscal_position.id})
        )

    def _receipt_price_unit(self, product, partner, currency=None):
        """Return the unit cost that purchase_stock gives to the receipt of a
        purchase order line of ``product`` bought from ``partner`` (in an order
        in ``currency``, by default the one Odoo proposes), with the unit, the
        quantity and the price Odoo takes from the vendor price."""
        order_form = Form(self.env["purchase.order"])
        order_form.partner_id = partner
        if currency:
            order_form.currency_id = currency
        with order_form.order_line.new() as line:
            line.product_id = product
        order = order_form.save()
        self.assertEqual(order.order_line.product_qty, 1.0)
        return order.order_line._get_stock_move_price_unit()

    def test_discount_only(self):
        cost, notes = self._net_cost(100.0, discount=10.0)
        self.assertAlmostEqual(cost, 90.0)
        self.assertEqual(notes, [])

    def test_excluded_tax_is_not_removed(self):
        cost, notes = self._net_cost(100.0, taxes=self.tax_21, discount=10.0)
        self.assertAlmostEqual(cost, 90.0)
        self.assertEqual(notes, [])

    def test_skipping_compute_all_gives_the_same_cost(self):
        # compute_all is skipped when it cannot change the cost: check that it
        # would indeed return the price for such a tax.
        Supplierinfo = self.env["product.supplierinfo"]
        changes_amount = Supplierinfo._cost_from_supplierinfo_taxes_change_amount
        self.assertFalse(changes_amount(self.tax_21))
        self.assertTrue(changes_amount(self.tax_21_included))
        self.assertTrue(changes_amount(self.tax_half_deductible))
        result = self.tax_21.compute_all(
            90.0,
            currency=self.company.currency_id,
            quantity=1.0,
            rounding_method="round_globally",
        )
        cost, _notes = self._net_cost(100.0, taxes=self.tax_21, discount=10.0)
        self.assertAlmostEqual(result["total_void"], 90.0)
        self.assertAlmostEqual(cost, result["total_void"])

    def test_included_tax_is_removed(self):
        cost, notes = self._net_cost(121.0, taxes=self.tax_21_included)
        self.assertAlmostEqual(cost, 100.0)
        self.assertEqual(notes, ["Taxes included in the price removed"])

    def test_non_deductible_tax_is_added(self):
        # 21 % of 100, half of it without account: 10.5 are part of the cost.
        cost, notes = self._net_cost(100.0, taxes=self.tax_half_deductible)
        self.assertAlmostEqual(cost, 110.5)
        self.assertEqual(notes, ["Non-deductible tax added"])

    def test_included_non_deductible_tax(self):
        tax = self._create_tax(
            "Test VAT 21% included half deductible",
            21.0,
            included=True,
            deductible=50.0,
        )
        cost, notes = self._net_cost(121.0, taxes=tax)
        self.assertAlmostEqual(cost, 110.5)
        self.assertEqual(
            notes, ["Taxes included in the price removed", "Non-deductible tax added"]
        )

    def test_vendor_unit_box(self):
        cost, notes = self._net_cost(120.0, product_uom_id=self.uom_box.id)
        self.assertAlmostEqual(cost, 10.0)
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("Converted from"))
        self.assertTrue(notes[0].endswith("per Box of 12"))

    def test_currency_conversion(self):
        cost, notes = self._net_cost(50.0, currency_id=self.currency_eur.id)
        self.assertAlmostEqual(cost, self._in_company_currency(50.0))
        self.assertNotAlmostEqual(cost, 50.0)
        self.assertEqual(notes, ["Converted from EUR"])

    def test_rounding(self):
        cost, _notes = self._net_cost(10.0, product_uom_id=self.uom_box.id)
        expected = float_round(10.0 / 12, precision_digits=self.price_digits)
        self.assertAlmostEqual(cost, expected, places=6)
        self.assertAlmostEqual(cost, round(cost, self.price_digits), places=9)
        # The vendor price is rounded before the discount, like the unit price
        # of a purchase order line: 10.125 gives 10.13, and 9.12 at 10 % off
        # (9.11 when rounded only at the end).
        cost, _notes = self._net_cost(10.125, discount=10.0)
        digits = max(self.company.currency_id.decimal_places, self.price_digits)
        expected = float_round(
            float_round(10.125, precision_digits=digits) * 0.9,
            precision_digits=self.price_digits,
        )
        self.assertAlmostEqual(cost, expected, places=6)

    def test_all_steps_together(self):
        # 242 EUR per box, 50 % off, 21 % included: 100 EUR per box.
        cost, notes = self._net_cost(
            242.0,
            taxes=self.tax_21_included,
            discount=50.0,
            product_uom_id=self.uom_box.id,
            currency_id=self.currency_eur.id,
        )
        self.assertAlmostEqual(cost, self._in_company_currency(100.0 / 12))
        self.assertEqual(len(notes), 3)

    def test_fiscal_position_maps_taxes(self):
        importer = self._mapping_vendor(
            "Importer",
            self.tax_21,
            {"name": "Test VAT 21% import", "amount": 21.0, "deductible": 50.0},
        )
        mapped_cost, _notes = self._net_cost(
            100.0, taxes=self.tax_21, partner=importer
        )
        plain_cost, _notes = self._net_cost(100.0, taxes=self.tax_21)
        self.assertAlmostEqual(mapped_cost, 110.5)
        self.assertAlmostEqual(plain_cost, 100.0)

    def test_fiscal_position_removes_included_tax(self):
        exempt = self._mapping_vendor(
            "Exempt Vendor",
            self.tax_21_included,
            {"name": "Test VAT exempt", "amount": 0.0},
        )
        cost, notes = self._net_cost(121.0, taxes=self.tax_21_included, partner=exempt)
        self.assertAlmostEqual(cost, 100.0)
        self.assertEqual(notes, ["Taxes included in the price removed"])

    def test_incompatible_units(self):
        uom_litre = self.env["uom.uom"].create(
            {"name": "Test Litre", "relative_factor": 1.0}
        )
        product = self._create_product("Bulk Product")
        litre_row = self._create_row(
            product, self.vendor_a, 10.0, product_uom_id=uom_litre.id
        )
        box_row = self._create_row(
            product, self.vendor_a, 10.0, product_uom_id=self.uom_box.id
        )
        self.assertFalse(litre_row._cost_from_supplierinfo_uom_compatible(product))
        self.assertTrue(box_row._cost_from_supplierinfo_uom_compatible(product))

    def test_equal_to_purchase_receipt(self):
        """The cost is the value per unit that Odoo gives to the receipt of a
        purchase order line of one unit (purchase_stock's
        ``_get_stock_move_price_unit``)."""
        order_line = type(self.env["purchase.order.line"])
        if not hasattr(order_line, "_get_stock_move_price_unit"):
            self.skipTest("purchase_stock is not installed")
        importer = self._mapping_vendor(
            "Importer",
            self.tax_21,
            {"name": "Test VAT 21% import", "amount": 21.0, "deductible": 50.0},
        )
        digits = max(self.company.currency_id.decimal_places, self.price_digits)
        rounded = float_round(10.125, precision_digits=digits)
        # Name, vendor price, taxes of the product, vendor, values of the
        # vendor price, currency of the order and expected cost.
        cases = [
            ("plain row", 100.0, None, None, {"discount": 10.0}, None, 90.0),
            (
                "included tax",
                121.0,
                self.tax_21_included,
                None,
                {"discount": 10.0},
                None,
                90.0,
            ),
            (
                "box of 12",
                120.0,
                None,
                None,
                {"product_uom_id": self.uom_box.id},
                None,
                10.0,
            ),
            (
                "EUR row",
                50.0,
                None,
                None,
                {"currency_id": self.currency_eur.id},
                self.currency_eur,
                self._in_company_currency(50.0),
            ),
            (
                "half deductible tax",
                100.0,
                self.tax_half_deductible,
                None,
                {},
                None,
                110.5,
            ),
            ("fiscal position", 100.0, self.tax_21, importer, {}, None, 110.5),
            (
                "3 decimals and a discount",
                10.125,
                None,
                None,
                {"discount": 10.0},
                None,
                float_round(rounded * 0.9, precision_digits=self.price_digits),
            ),
        ]
        for name, price, taxes, partner, row_values, currency, expected in cases:
            with self.subTest(case=name):
                vendor = partner or self.vendor_a
                product = self._create_product(
                    f"Received Product ({name})",
                    supplier_taxes_id=[Command.set(taxes.ids if taxes else [])],
                )
                row = self._create_row(product, vendor, price, **row_values)
                cost, _notes = row._get_cost_from_supplierinfo(
                    product, self.company, self.today
                )
                self.assertAlmostEqual(cost, expected, places=self.price_digits)
                self.assertAlmostEqual(
                    cost,
                    self._receipt_price_unit(product, vendor, currency),
                    places=self.price_digits,
                )
