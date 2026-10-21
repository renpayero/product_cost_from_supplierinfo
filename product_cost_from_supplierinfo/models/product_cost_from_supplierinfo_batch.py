# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_compare, split_every

SOURCE_SELECTION = [
    ("supplierinfo", "Selected vendor prices"),
    ("product", "Main vendor of the selected products"),
]
# Products per round of cost writes when reverting.
REVERT_CHUNK_SIZE = 200


class ProductCostFromSupplierinfoBatch(models.Model):
    _name = "product.cost.from.supplierinfo.batch"
    _description = "Cost Update"
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Applied by",
        readonly=True,
        ondelete="set null",
        default=lambda self: self.env.user,
    )
    date = fields.Datetime(
        string="Applied on",
        required=True,
        readonly=True,
        default=fields.Datetime.now,
    )
    source = fields.Selection(selection=SOURCE_SELECTION, readonly=True)
    pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Sale price in",
        readonly=True,
        ondelete="set null",
    )
    state = fields.Selection(
        selection=[
            ("done", "Applied"),
            ("partial", "Partially reverted"),
            ("reverted", "Reverted"),
        ],
        string="Status",
        required=True,
        readonly=True,
        default="done",
    )
    count_updated = fields.Integer(string="Updated", readonly=True)
    count_unchanged = fields.Integer(string="Unchanged", readonly=True)
    count_skipped = fields.Integer(string="Skipped", readonly=True)
    revert_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Reverted by",
        readonly=True,
        ondelete="set null",
    )
    revert_date = fields.Datetime(string="Reverted on", readonly=True)
    line_ids = fields.One2many(
        comodel_name="product.cost.from.supplierinfo.batch.line",
        inverse_name="batch_id",
        string="Lines",
        readonly=True,
    )

    @api.depends("line_ids.partner_id")
    def _compute_name(self):
        for batch in self:
            partners = batch.line_ids.partner_id
            vendor = (
                partners.display_name
                if len(partners) == 1
                else self.env._("Several vendors")
            )
            batch.name = self.env._(
                "%(vendor)s · Products: %(count)s",
                vendor=vendor,
                count=len(batch.line_ids),
            )

    def action_revert(self):
        """Put back the previous cost of the products of these updates.

        A product is only reverted while its cost is still the one this update
        wrote, no later update changed it and its cost method is still the
        standard one; otherwise it is left as it is and the line says why. The
        costs are written with the rights of the current user, so that Odoo
        records the change in the cost history like any other cost change.
        Return a notification with the number of products reverted and left.
        """
        self.env["product.product"].check_access("write")
        digits = self.env["decimal.precision"].precision_get("Product Price")
        Line = self.env["product.cost.from.supplierinfo.batch.line"]
        fifo_note = self.env._("Cost method is FIFO/AVCO")
        later_note = self.env._("Changed by a later cost update")
        modified_note = self.env._("Cost modified after this change")
        reverted_count = left_count = 0
        for batch in self:
            company = batch.company_id
            Product = self.env["product.product"].with_company(company)
            pending = batch.line_ids.filtered(lambda line: not line.reverted)
            reverted_ids = []
            left_ids_by_note = defaultdict(list)
            for chunk in split_every(REVERT_CHUNK_SIZE, pending.ids, pending.browse):
                last_line_ids = chunk._cost_from_supplierinfo_last_line_ids(company)
                product_ids_by_cost = defaultdict(list)
                for line in chunk:
                    product = line.product_id.with_company(company)
                    if product._cost_from_supplierinfo_cost_is_computed():
                        note = fifo_note
                    # Reverting would undo the later update, which would still
                    # be recorded as applied.
                    elif last_line_ids.get(product.id, 0) > line.id:
                        note = later_note
                    elif float_compare(
                        product.standard_price, line.new_cost, precision_digits=digits
                    ):
                        note = modified_note
                    else:
                        product_ids_by_cost[line.old_cost].append(product.id)
                        reverted_ids.append(line.id)
                        continue
                    left_ids_by_note[note].append(line.id)
                for cost, product_ids in product_ids_by_cost.items():
                    Product.browse(product_ids).write({"standard_price": cost})
                self.env.flush_all()
            reverted = Line.browse(reverted_ids)
            # sudo: the history is only written by this module.
            reverted.sudo().write({"reverted": True, "revert_note": False})
            for note, line_ids in left_ids_by_note.items():
                Line.browse(line_ids).sudo().write({"revert_note": note})
            reverted_count += len(reverted_ids)
            left_count += sum(map(len, left_ids_by_note.values()))
            # Nothing reverted: the update stays as it was.
            if not reverted:
                continue
            reverted.product_id._cost_from_supplierinfo_schedule_pos_refresh(company)
            batch.sudo().write(
                {
                    "state": (
                        "reverted"
                        if all(batch.line_ids.mapped("reverted"))
                        else "partial"
                    ),
                    "revert_user_id": self.env.uid,
                    "revert_date": fields.Datetime.now(),
                }
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": (
                    self.env._("Costs reverted")
                    if reverted_count
                    else self.env._("Nothing was reverted")
                ),
                "message": self.env._(
                    "Reverted products: %(reverted)s. Products left as they are: "
                    "%(left)s.",
                    reverted=reverted_count,
                    left=left_count,
                ),
                "type": "success" if reverted_count else "warning",
                "sticky": False,
                # Closing reloads the form of the update.
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class ProductCostFromSupplierinfoBatchLine(models.Model):
    _name = "product.cost.from.supplierinfo.batch.line"
    _description = "Cost Update Line"
    _order = "batch_id, id"

    batch_id = fields.Many2one(
        comodel_name="product.cost.from.supplierinfo.batch",
        string="Cost Update",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        related="batch_id.company_id", store=True, index=True
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
    )
    default_code = fields.Char(related="product_id.default_code")
    supplierinfo_id = fields.Many2one(
        comodel_name="product.supplierinfo",
        string="Vendor Price",
        readonly=True,
        ondelete="set null",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Vendor",
        readonly=True,
        ondelete="set null",
    )
    old_cost = fields.Float(
        string="Previous cost", min_display_digits="Product Price", readonly=True
    )
    new_cost = fields.Float(
        string="New cost", min_display_digits="Product Price", readonly=True
    )
    reverted = fields.Boolean(readonly=True)
    revert_note = fields.Char(readonly=True)

    def _cost_from_supplierinfo_last_line_ids(self, company):
        """Return ``{product id: id of its last line}`` among the lines of the
        cost updates of ``company`` that come after the first line of ``self``,
        are about the products of ``self`` and are not reverted."""
        # sudo: every later update counts, whatever the companies the user
        # works in.
        groups = self.sudo()._read_group(
            [
                ("product_id", "in", self.product_id.ids),
                ("company_id", "=", company.id),
                ("id", ">", min(self.ids)),
                ("reverted", "=", False),
            ],
            ["product_id"],
            ["id:max"],
        )
        return {product.id: last_id for product, last_id in groups}
