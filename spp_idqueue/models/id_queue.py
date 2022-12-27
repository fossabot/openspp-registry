# Part of OpenSPP. See LICENSE file for full copyright and licensing details.

from datetime import date, datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.queue_job.delay import group


class OpenSPPIDQueue(models.Model):
    _name = "spp.print.queue.id"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "ID Queue"
    _order = "id DESC"

    JOB_SIZE = 20

    name = fields.Char("Request Name", compute="_compute_name")
    id_type = fields.Many2one("g2p.id.type", required=True)
    idpass_id = fields.Many2one("spp.id.pass")
    requested_by = fields.Many2one("res.users", required=True)
    approved_by = fields.Many2one("res.users")
    printed_by = fields.Many2one("res.users")
    registrant_id = fields.Many2one("res.partner", required=True)
    area_id = fields.Many2one("spp.area", related="registrant_id.area_id", store=True)
    date_requested = fields.Date()
    date_approved = fields.Date()
    date_printed = fields.Date()
    date_distributed = fields.Date()
    status = fields.Selection(
        [
            ("new", "New"),
            ("approved", "Approved"),
            ("generating", "Generating"),
            ("generated", "Generated"),
            ("printed", "Printed"),
            ("distributed", "Distributed"),
            ("cancelled", "Cancelled"),
        ],
        default="new",
    )
    id_pdf = fields.Binary("ID PASS")
    id_pdf_filename = fields.Char("ID File Name")

    batch_id = fields.Many2one("spp.print.queue.batch", string="Batch")

    @api.depends("registrant_id", "idpass_id")
    def _compute_name(self):
        """
        Compute Name
        These are used to compute the name of the queue base on
        registrant name and template name
        """
        for rec in self:
            rec.name = f"{rec.registrant_id.name or ''} - {rec.idpass_id.name or ''}"

    def on_approve(self):
        """
        On Approve
        These are used to approve or validate the request
        """
        for rec in self:
            rec.date_approved = date.today()
            rec.approved_by = self.env.user.id
            rec.status = "approved"
            message = _("{} validated this request on {}.").format(
                self.env.user.name, datetime.now().strftime("%B %d, %Y at %H:%M")
            )
            rec.save_to_mail_thread(message)

    def on_generate(self):
        """
        On Generate
        These are used to call the generation of cards function
        """
        # Make sure the ID is in the correct state before generating
        # we allow to re-generate cards
        self.generate_cards()

    def on_print(self):
        """
        On Print
        These are used to set the request as printed
        """

        # as we return the PDF, we need to make sure that there is only 1 card selected
        self.ensure_one()

        # Make sure the ID is in the correct state before printing
        if self.filtered(lambda x: x.status not in ["generated", "approved"]):
            raise ValidationError(_("ID must be approved before printing"))

        if self.filtered(lambda x: x.batch_id):
            raise ValidationError(_("ID in a batch cannot be printed individually"))

        if self.status == "approved":
            # Not generated yet, generate it
            res_id = self.generate_card(self)
        else:
            res_id = self.id_pdf

        self.date_printed = date.today()
        self.printed_by = self.env.user.id
        self.status = "printed"
        message = _("{} printed this request on {}.").format(
            self.env.user.name, datetime.now().strftime("%B %d, %Y at %H:%M")
        )
        self.save_to_mail_thread(message)
        return res_id

    def generate_cards(self):
        """
        Generate Cards
        These are used to generate the ID from the request
        """
        if self.filtered(
            lambda x: x.status
            not in ["generating", "generated", "approved", "added_to_batch"]
        ):
            raise ValidationError(_("ID must be approved before printing"))

        for rec in self:
            rec.generate_card(rec)
            rec.status = "generated"
            message = _("{} generated this request on {}.").format(
                self.env.user.name, datetime.now().strftime("%B %d, %Y at %H:%M")
            )
            rec.save_to_mail_thread(message)

    def generate_card(self, card):
        """
        Generate ID card
        Override this method to change the backend used to generate the ID card
        """
        if card.id_type.id == self.env.ref("spp_idpass.id_type_idpass").id:
            vals = {"idpass": self.idpass_id.id, "id_queue": self.id}
            self.registrant_id.send_idpass_parameters(vals)

    def on_cancel(self):
        """
        On Cancel
        These are used to cancel the request
        """
        if self.filtered(lambda x: x.status in ["printed", "distributed"]):
            raise ValidationError(_("ID cannot be canceled if it has been printed"))
        for rec in self:
            rec.status = "cancelled"
            message = _("{} cancelled this request on {}.").format(
                self.env.user.name, datetime.now().strftime("%B %d, %Y at %H:%M")
            )
            rec.save_to_mail_thread(message)

    def on_distribute(self):
        """
        On Approve
        These are used to set the request as distributed
        """
        if not self.filtered(lambda x: x.status in ["printed"]):
            raise ValidationError(
                _("ID can only be distributed if it has been printed")
            )
        for rec in self:
            rec.date_distributed = date.today()
            rec.status = "distributed"
            message = _("{} distributed this request on {}.").format(
                self.env.user.name, datetime.now().strftime("%B %d, %Y at %H:%M")
            )
            rec.save_to_mail_thread(message)

    def validate_requests(self):
        """
        Validate Requests
        These are used to approve or validate multiple requests
        via Server Action
        """
        if self.env.context.get("active_ids"):
            queue_id = self.env["spp.print.queue.id"].search(
                [
                    ("id", "in", self.env.context.get("active_ids")),
                    ("status", "=", "new"),
                ]
            )
            if queue_id:
                max_rec = len(queue_id)
                for rec in queue_id:
                    rec.date_approved = date.today()
                    rec.approved_by = self.env.user.id
                    rec.status = "approved"
                    message = _("{} validated this request on {}.").format(
                        self.env.user.name,
                        datetime.now().strftime("%B %d, %Y at %H:%M"),
                    )
                    rec.save_to_mail_thread(message)

                message = _("%s request(s) are validated.", max_rec)
                kind = "info"
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("ID Requests"),
                        "message": message,
                        "sticky": True,
                        "type": kind,
                        "next": {
                            "type": "ir.actions.act_window_close",
                        },
                    },
                }

    def generate_validate_requests(self):
        """
        Generate Validated Requests
        These are used to generate multiple validated requests
        by creating a Queue Job to work on background
        """
        queue_ids = self.env["spp.print.queue.id"].search(
            [
                ("id", "in", self.env.context.get("active_ids")),
                ("status", "=", "approved"),
            ]
        )
        if queue_ids:
            queue_datas = []
            jobs = []
            ctr2 = 1
            max_rec = len(queue_ids)
            for ctr, queued_id in enumerate(queue_ids, 1):
                queued_id.status = "generating"
                message = _("{} started to generate this request on {}.").format(
                    self.env.user.name, datetime.now().strftime("%B %d, %Y at %H:%M")
                )
                queued_id.save_to_mail_thread(message)
                queue_datas.append(queued_id.id)
                if ctr2 == self.JOB_SIZE or ctr == max_rec:
                    ctr2 = 0
                    jobs.append(self.delayable()._generate_multi_cards(queue_datas))
                    queue_datas = []
                ctr2 += 1
            main_job = group(*jobs)
            main_job.delay()

            message = _("%s request(s) are now being generated.", max_rec)
            kind = "info"
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("ID Requests"),
                    "message": message,
                    "sticky": True,
                    "type": kind,
                    "next": {
                        "type": "ir.actions.act_window_close",
                    },
                },
            }

    def _generate_multi_cards(self, queue_ids):
        """
        Generate Multi Cards
        These are called by the Job Queue created from generate_validate_requests
        """
        queued_ids = self.env["spp.print.queue.id"].search([("id", "in", queue_ids)])
        queued_ids.generate_cards()

    def print_requests(self):
        """
        Print Requests
        These are used to set multiple requests as printed
        """
        if self.env.context.get("active_ids"):
            queue_id = self.env["spp.print.queue.id"].search(
                [
                    ("id", "in", self.env.context.get("active_ids")),
                    ("status", "=", "generated"),
                ]
            )
            if queue_id:
                max_rec = len(queue_id)
                for rec in queue_id:
                    rec.date_printed = date.today()
                    rec.printed_by = self.env.user.id
                    rec.status = "printed"
                    message = _("{} printed this request on {}.").format(
                        self.env.user.name,
                        datetime.now().strftime("%B %d, %Y at %H:%M"),
                    )
                    rec.save_to_mail_thread(message)

                message = _("%s request(s) are printed.", max_rec)
                kind = "info"
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("ID Requests"),
                        "message": message,
                        "sticky": True,
                        "type": kind,
                        "next": {
                            "type": "ir.actions.act_window_close",
                        },
                    },
                }

    def distribute_requests(self):
        """
        Distribute Requests
        These are used to set multiple requests as distributed
        """
        if self.env.context.get("active_ids"):
            queue_id = self.env["spp.print.queue.id"].search(
                [
                    ("id", "in", self.env.context.get("active_ids")),
                    ("status", "=", "printed"),
                ]
            )
            if queue_id:
                max_rec = len(queue_id)
                for rec in queue_id:
                    rec.date_distributed = date.today()
                    rec.status = "distributed"
                    message = _("{} distributed this request on {}.").format(
                        self.env.user.name,
                        datetime.now().strftime("%B %d, %Y at %H:%M"),
                    )
                    rec.save_to_mail_thread(message)

                message = _("%s request(s) are distributed.", max_rec)
                kind = "info"
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("ID Requests"),
                        "message": message,
                        "sticky": True,
                        "type": kind,
                        "next": {
                            "type": "ir.actions.act_window_close",
                        },
                    },
                }

    def save_to_mail_thread(self, message):
        """
        Save to Mail Thread
        These are being used or called to post to mail_thread
        """
        for rec in self:
            rec.message_post(body=message)

    def open_request_form(self):
        """
        Open Request Form
        These are being used to open the request form
        """
        return {
            "name": "ID Request",
            "view_mode": "form",
            "res_model": self._name,
            "res_id": self.id,
            "view_id": self.env.ref("spp_idqueue.view_spp_idqueue_form").id,
            "type": "ir.actions.act_window",
            "target": "new",
            "flags": {"mode": "readonly"},
        }


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    """
    Add Auto Approve configuration to automatically set
    requests as 'approved' upon creation if auto_approve_id_request
    is True
    """

    auto_approve_id_request = fields.Boolean(
        default=True,
        help="Check if you want to auto-approve ID requests",
        string="Auto-approve ID Requests",
    )

    def set_values(self):
        """
        Get Values
        These are used to Set the auto_approve_id_request value
        """
        res = super(ResConfigSettings, self).set_values()
        self.env["ir.config_parameter"].set_param(
            "spp_id_queue.auto_approve_id_request", self.auto_approve_id_request
        )
        return res

    @api.model
    def get_values(self):
        """
        Get Values
        These are used to Get the auto_approve_id_request value
        """
        res = super(ResConfigSettings, self).get_values()
        params = self.env["ir.config_parameter"].sudo()
        res.update(
            auto_approve_id_request=params.get_param(
                "spp_id_queue.auto_approve_id_request"
            )
        )
        return res
