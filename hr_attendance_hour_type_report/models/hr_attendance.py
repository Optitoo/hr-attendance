# Copyright 2021 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import datetime as dt
from zoneinfo import ZoneInfo
import logging

import pytz

from odoo import _, api, exceptions, fields, models

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    worked_hours_nighttime = fields.Float(
        string="Night hours", compute="_compute_worked_hours", store=True
    )
    worked_hours_daytime = fields.Float(
        string="Day hours",
        compute="_compute_worked_hours",
        store=True,
        readonly=True,
    )
    date = fields.Date(
        help="date of the attendance, from the payroll point of view",
        compute="_compute_date",
        store=True,
    )
    date_type = fields.Selection(
        [("normal", "Weekday"), ("sunday", "Sunday"), ("holiday", "Public Holiday")],
        compute="_compute_date_type",
        store=True,
    )

    @api.depends("date")
    def _compute_date_type(self):
        for rec in self:
            if rec.date.weekday() == 6:
                rec.date_type = "sunday"
            elif rec.employee_id._get_public_holidays(rec.date, rec.date):
                rec.date_type = "holiday"
            else:
                rec.date_type = "normal"

    @api.depends("check_in")
    def _compute_date(self):
        UTC = pytz.timezone("utc")        
        for rec in self:
            tz = rec.employee_id.tz
            check_in = rec.check_in
            if not check_in.tzinfo:
                check_in = UTC.localize(check_in)
            check_in_tz = check_in.astimezone(pytz.timezone(tz))
            rec.date = check_in_tz.date()

    @api.depends("check_in", "check_out")
    def _compute_worked_hours(self):
        res = super()._compute_worked_hours()
        for rec in self:
            rec.worked_hours_nighttime = 0
            rec.worked_hours_daytime = 0
            if not rec.check_out:
                continue
            if rec.worked_hours > 24:
                raise exceptions.UserError(
                    _("More than 24h of work in 1 shift is forbidden")
                )
            night_start = int(rec.employee_id.company_id.hr_night_work_hour_start) or 0
            night_end = int(rec.employee_id.company_id.hr_night_work_hour_end) or 0    
            rec.worked_hours_nighttime = calculate_night_hours(rec.check_in, rec.check_out, night_start, night_end, rec.employee_id.tz)
            rec.worked_hours_daytime = rec.worked_hours - rec.worked_hours_nighttime
        return res

def calculate_night_hours(check_in, check_out, 
                          night_start_hour=1, night_end_hour=5,
                          timezone="Europe/Paris", 
                          round_to="none"):
    """
    Calcule les heures de nuit entre check_in et check_out dans un fuseau horaire donné.

    Params:
        - check_in / check_out : datetime naïfs ou aware (seront convertis en timezone locale)
        - night_start_hour / night_end_hour : heures de début et fin de la nuit (int)
        - timezone : nom du fuseau horaire (ex: "Europe/Paris")
        - round_to : "none" | "hour" | "quarter"
        - return_format : "float" | "hh:mm"

    Return:
        - heures de nuit (float ou string selon format)
    """
    tz = ZoneInfo(timezone)

    # Conversion en timezone locale si nécessaire
    if check_in.tzinfo is None:
        check_in = check_in.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    else:
        check_in = check_in.astimezone(tz)

    if check_out.tzinfo is None:
        check_out = check_out.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    else:
        check_out = check_out.astimezone(tz)

    total_night_hours = 0.0
    start_day = (check_in - dt.timedelta(days=1)).date()
    end_day = (check_out + dt.timedelta(days=1)).date()

    for day in range((end_day - start_day).days + 1):
        current_day = start_day + dt.timedelta(days=day)

        night_start = dt.datetime.combine(current_day, dt.time(hour=night_start_hour), tzinfo=tz)
        night_end = dt.datetime.combine(current_day, dt.time(hour=night_end_hour), tzinfo=tz)

        if night_end_hour <= night_start_hour:
            # La plage traverse minuit (ex: 22h - 6h)
            night_end += dt.timedelta(days=1)

        overlap_start = max(night_start, check_in)
        overlap_end = min(night_end, check_out)

        if overlap_end > overlap_start:
            total_night_hours += (overlap_end - overlap_start).total_seconds() / 3600.0

    # Arrondi
    if round_to == "hour":
        total_night_hours = round(total_night_hours)
    elif round_to == "quarter":
        total_night_hours = round(total_night_hours * 4) / 4

    return round(total_night_hours, 2)