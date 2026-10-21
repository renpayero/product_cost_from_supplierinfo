# Copyright 2026 Renzo Payero, DakoDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Product Cost from Supplierinfo",
    "summary": "Set the product cost from the vendor price, with preview and undo",
    "version": "19.0.1.0.0",
    "category": "Supply Chain/Purchase",
    "author": "Renzo Payero, DakoDev",
    "website": "https://github.com/renpayero/product_cost_from_supplierinfo",
    "license": "AGPL-3",
    "depends": ["purchase"],
    "data": [
        "security/product_cost_from_supplierinfo_security.xml",
        "security/ir.model.access.csv",
        "wizards/product_cost_from_supplierinfo_wizard_views.xml",
        "views/product_cost_from_supplierinfo_batch_views.xml",
    ],
    "installable": True,
}
