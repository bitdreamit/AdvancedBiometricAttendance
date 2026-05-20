# src/core/attendance_processor.py
"""
Processes raw punch records into clean IN/OUT pairs with calculated
late minutes, early-out minutes, overtime and work status.

Called by AttendanceService every sync cycle.
"""
import logging
from datetime import datetime, date, timedelta, time as dtime
from typing import List, Dict, Optional, Tuple

try:
    from src.core.database import DatabaseManager
except ImportError:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


def _parse_time(t: str) -> dtime:
    """Parse HH:MM string to time object."""
    h, m = map(int, t.split(':'))
    return dtime(h, m)


def _parse_dt(s: str) -> Optional[datetime]:
    """Parse ISO timestamp string to datetime."""
    if not s:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


class AttendanceProcessor:
    """Converts raw punch events → attendance_log rows with full calculations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def process_date(self, work_date: str) -> int:
        """
        Process all raw punches for a single date.
        Returns number of employees processed.
        """
        punches = self.db.get_attendance_by_date(work_date)
        if not punches:
            return 0

        # Group punches by employee_id
        by_employee: Dict[int, List[Dict]] = {}
        for p in punches:
            emp_id = p.get('employee_id')
            if not emp_id:
                continue
            by_employee.setdefault(emp_id, []).append(p)

        processed = 0
        for emp_id, emp_punches in by_employee.items():
            try:
                self._process_employee_day(emp_id, work_date, emp_punches)
                processed += 1
            except Exception as e:
                logger.error(f"Processing error for employee {emp_id} on {work_date}: {e}")

        logger.info(f"Processed {work_date}: {processed} employees")
        return processed

    def process_range(self, from_date: str, to_date: str) -> int:
        """Process all dates in a range."""
        start = datetime.strptime(from_date, '%Y-%m-%d').date()
        end   = datetime.strptime(to_date,   '%Y-%m-%d').date()
        total = 0
        current = start
        while current <= end:
            total += self.process_date(current.isoformat())
            current += timedelta(days=1)
        return total

    def _process_employee_day(self, employee_id: int, work_date: str,
                               punches: List[Dict]):
        """Compute attendance_log row for one employee on one day."""
        shift = self.db.get_employee_shift(employee_id, work_date)
        sorted_punches = sorted(punches, key=lambda p: p['punch_time'])

        # First punch = check_in, last punch = check_out
        check_in_row  = sorted_punches[0]
        check_out_row = sorted_punches[-1] if len(sorted_punches) > 1 else None

        check_in  = _parse_dt(check_in_row['punch_time'])
        check_out = _parse_dt(check_out_row['punch_time']) if check_out_row else None

        working_minutes    = 0
        late_minutes       = 0
        early_out_minutes  = 0
        overtime_minutes   = 0
        status             = 'present'

        if shift and check_in:
            shift_start = _parse_time(shift['start_time'])
            shift_end   = _parse_time(shift['end_time'])

            # Handle overnight shift
            shift_start_dt = datetime.combine(check_in.date(), shift_start)
            if shift.get('is_overnight') and shift_end < shift_start:
                shift_end_dt = datetime.combine(
                    check_in.date() + timedelta(days=1), shift_end
                )
            else:
                shift_end_dt = datetime.combine(check_in.date(), shift_end)

            grace_late      = shift.get('grace_late', 15)
            grace_early_out = shift.get('grace_early_out', 10)
            overtime_after  = shift.get('overtime_after', 30)

            # Late calculation
            if not shift.get('is_flexible'):
                diff_late = (check_in - shift_start_dt).total_seconds() / 60
                if diff_late > grace_late:
                    late_minutes = int(diff_late - grace_late)

            # Working time & early out / overtime
            if check_out:
                working_minutes = max(
                    0, int((check_out - check_in).total_seconds() / 60)
                )

                if not shift.get('is_flexible'):
                    diff_early = (shift_end_dt - check_out).total_seconds() / 60
                    if diff_early > grace_early_out:
                        early_out_minutes = int(diff_early - grace_early_out)

                    diff_ot = (check_out - shift_end_dt).total_seconds() / 60
                    if diff_ot > overtime_after:
                        overtime_minutes = int(diff_ot - overtime_after)

                # Half-day detection
                shift_total = int((shift_end_dt - shift_start_dt).total_seconds() / 60)
                if shift_total > 0 and working_minutes < shift_total * 0.5:
                    status = 'half_day'

        # Check if date is approved leave
        leave = self._get_approved_leave(employee_id, work_date)
        if leave:
            status = 'on_leave'

        self.db.upsert_attendance_log(
            employee_id      = employee_id,
            work_date        = work_date,
            check_in         = check_in.isoformat()  if check_in  else None,
            check_out        = check_out.isoformat() if check_out else None,
            working_minutes  = working_minutes,
            late_minutes     = late_minutes,
            early_out_minutes= early_out_minutes,
            overtime_minutes = overtime_minutes,
            status           = status,
            shift_id         = shift['id'] if shift else None,
        )

    def _get_approved_leave(self, employee_id: int, work_date: str) -> Optional[Dict]:
        return self.db.fetchone(
            """SELECT * FROM leave_requests
               WHERE employee_id = ? AND status = 'approved'
                 AND from_date <= ? AND to_date >= ?""",
            (employee_id, work_date, work_date)
        )

    def mark_absent(self, work_date: str):
        """
        Mark all active employees with no punch on work_date as absent
        (unless they have approved leave).
        """
        employees   = self.db.get_employees(active_only=True)
        punched_ids = {
            p['employee_id']
            for p in self.db.get_attendance_by_date(work_date)
            if p.get('employee_id')
        }

        absent_count = 0
        for emp in employees:
            emp_id = emp['id']
            if emp_id in punched_ids:
                continue

            existing = self.db.fetchone(
                "SELECT id FROM attendance_log WHERE employee_id=? AND work_date=?",
                (emp_id, work_date)
            )
            if existing:
                continue  # already processed

            leave = self._get_approved_leave(emp_id, work_date)
            status = 'on_leave' if leave else 'absent'

            self.db.upsert_attendance_log(
                employee_id=emp_id,
                work_date=work_date,
                status=status
            )
            absent_count += 1

        logger.info(f"Marked {absent_count} employees absent/leave on {work_date}")
