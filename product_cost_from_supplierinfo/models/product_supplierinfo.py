# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, models
from odoo.tools import float_round, formatLang


class ProductSupplierinfo(models.Model):
    _inherit = "product.supplierinfo"

    def _cost_from_supplierinfo_uom_compatible(self, product):
        """Return whether the unit of this vendor price converts to the unit of
        ``product``. Odoo 19 units have no categories: converting between two
        units without a common reference unit gives a wrong value silently."""
        self.ensure_one()
        vendor_uom = self.sudo().product_uom_id
        product_uom = product.sudo().uom_id
        return vendor_uom == product_uom or vendor_uom._has_common_reference(
            product_uom
        )

    def _get_cost_from_supplierinfo(self, product, company, date, fiscal_position=None):
        """Return ``(cost, notes)``: the unit cost of ``product`` in ``company``
        when it is bought on this vendor price, and the conversions applied.

        The cost is the one of a purchase order line for one unit, in the
        currency of the vendor price, valued on receipt like purchase_stock
        does (``_get_stock_move_price_unit``):

        1. the fiscal position of the vendor maps the purchase taxes;
        2. the price is rounded like the unit price of the order line;
        3. the discount is applied;
        4. the taxes included in the price are removed and the non-deductible
           part of the taxes (distribution lines without account) is added;
        5. the price is converted to the product unit and to the company
           currency, and rounded to the "Product Price" precision.

        The units must be compatible, see ``_cost_from_supplierinfo_uom_compatible``.
        ``fiscal_position`` saves looking it up again for every vendor price of
        the same vendor; by default it is the one a purchase order would use.
        """
        self.ensure_one()
        # sudo: taxes and fiscal positions are only read to compute the cost,
        # and a product manager may not be allowed to read them.
        vendor_price = self.sudo().with_company(company)
        product = product.sudo().with_company(company)
        env = vendor_price.env
        currency = vendor_price.currency_id
        notes = []

        prod_taxes = product.supplier_taxes_id._filter_taxes_by_company(company)
        if fiscal_position is None:
            fiscal_position = env["account.fiscal.position"]._get_fiscal_position(
                vendor_price.partner_id
            )
        taxes = fiscal_position.with_env(env).map_tax(prod_taxes)

        # A tax included in the price that the fiscal position replaces is
        # removed first, as on a purchase order line.
        price = env["account.tax"]._fix_tax_included_price_company(
            vendor_price.price, prod_taxes, taxes, company
        )
        included_removed = currency.compare_amounts(price, vendor_price.price) != 0
        # Rounded like the unit price of the purchase order line, before the
        # receipt applies the discount. The line computes it in
        # _compute_price_unit_and_date_planned_and_name of
        # purchase/models/purchase_order_line.py: _fix_tax_included_price_company,
        # the conversion to the currency of the order (here the one of the
        # vendor price), then float_round(price_unit, precision_digits=max(
        # line.currency_id.decimal_places, "Product Price" digits)).
        digits = env["decimal.precision"].precision_get("Product Price")
        price = float_round(
            price, precision_digits=max(currency.decimal_places, digits)
        )
        price *= 1 - (vendor_price.discount or 0.0) / 100
        if taxes and self._cost_from_supplierinfo_taxes_change_amount(taxes):
            result = taxes.compute_all(
                price,
                currency=currency,
                quantity=1.0,
                product=product,
                partner=vendor_price.partner_id,
                rounding_method="round_globally",
            )
            excluded, void = result["total_excluded"], result["total_void"]
            included_removed |= currency.compare_amounts(excluded, price) != 0
            if currency.compare_amounts(void, excluded) != 0:
                notes.append(self.env._("Non-deductible tax added"))
            price = void
        if included_removed:
            notes.insert(0, self.env._("Taxes included in the price removed"))

        vendor_uom = vendor_price.product_uom_id
        if vendor_uom != product.uom_id:
            vendor_amount = formatLang(
                env, vendor_price.price, dp="Product Price", currency_obj=currency
            )
            notes.append(
                self.env._("Converted from %s per %s", vendor_amount, vendor_uom.name)
            )
            price = vendor_uom._compute_price(price, product.uom_id)
        if currency != company.currency_id:
            notes.append(self.env._("Converted from %s", currency.name))
            price = currency._convert(
                price, company.currency_id, company, date, round=False
            )
        return float_round(price, precision_digits=digits), notes

    @api.model
    def _cost_from_supplierinfo_taxes_change_amount(self, taxes):
        """Return whether ``taxes`` change the cost computed from a price.

        Only a tax included in the price, or a tax amount without account (not
        deductible), does: with any other tax ``compute_all`` returns the price
        as ``total_void``. Skipping it matters when thousands of costs are
        computed at once."""
        flat_taxes = taxes.flatten_taxes_hierarchy()
        return any(tax.price_include for tax in flat_taxes) or any(
            line.repartition_type == "tax" and not line.account_id
            for line in flat_taxes.invoice_repartition_line_ids
        )
