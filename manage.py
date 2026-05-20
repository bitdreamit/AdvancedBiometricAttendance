#!/usr/bin/env python3
# manage.py — Command-line management tool
"""
Usage:
  python manage.py employee add
  python manage.py employee list
  python manage.py employee shift <employee_code> <shift_name>

  python manage.py shift list
  python manage.py shift add

  python manage.py leave apply
  python manage.py leave approve <leave_id>
  python manage.py leave list [--employee <code>]

  python manage.py attendance report --date 2026-05-20
  python manage.py attendance monthly --year 2026 --month 5
  python manage.py attendance process --date 2026-05-20

  python manage.py biometric register
  python manage.py biometric list <employee_code>
"""
import sys
import os
import argparse
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.database import DatabaseManager
from src.core.attendance_processor import AttendanceProcessor
from src.utils.config_manager import ConfigManager


def get_db():
    cfg = ConfigManager().load_config('config/default_config.json')
    db_path = cfg.get('database', {}).get('path', 'data/att.db')
    return DatabaseManager(db_path=db_path)


# ── Pretty print helpers ─────────────────────────────────────────────────

def print_table(rows, columns=None):
    if not rows:
        print("  (no records)")
        return
    if not columns:
        columns = list(rows[0].keys())
    # Width per column
    widths = {c: max(len(str(c)), max(len(str(r.get(c, '') or '')) for r in rows))
              for c in columns}
    header = '  ' + '  '.join(str(c).upper().ljust(widths[c]) for c in columns)
    sep    = '  ' + '  '.join('-' * widths[c] for c in columns)
    print(header)
    print(sep)
    for r in rows:
        print('  ' + '  '.join(str(r.get(c, '') or '').ljust(widths[c]) for c in columns))


def banner(text):
    print()
    print('=' * 55)
    print(f'  {text}')
    print('=' * 55)


# ── Employee commands ────────────────────────────────────────────────────

def cmd_employee_add(db):
    banner("Register New Employee")
    code  = input("  Employee code (e.g. EMP001): ").strip()
    name  = input("  Full name               : ").strip()
    email = input("  Email (optional)        : ").strip() or None
    phone = input("  Phone (optional)        : ").strip() or None
    desig = input("  Designation (optional)  : ").strip() or None
    jdate = input(f"  Join date [{date.today()}] : ").strip() or date.today().isoformat()

    depts = db.get_departments()
    print("\n  Departments:")
    for d in depts:
        print(f"    [{d['id']}] {d['name']}")
    new_dept = input("  Department ID (or type new name): ").strip()
    if new_dept.isdigit():
        dept_id = int(new_dept)
    else:
        dept_id = db.add_department(new_dept)
        print(f"  Department '{new_dept}' created (id={dept_id})")

    emp_id = db.add_employee(code, name, dept_id, desig, email, phone, jdate)
    if emp_id:
        print(f"\n  ✓ Employee registered: {name} (id={emp_id}, code={code})")

        # Assign default shift
        shifts = db.get_shifts()
        print("\n  Available shifts:")
        for s in shifts:
            print(f"    [{s['id']}] {s['name']}  {s['start_time']}-{s['end_time']}")
        shift_id = input("  Assign shift ID (Enter to skip): ").strip()
        if shift_id.isdigit():
            db.assign_shift(emp_id, int(shift_id))
            print(f"  ✓ Shift assigned")
    else:
        print(f"\n  ✗ Failed — employee code '{code}' may already exist")


def cmd_employee_list(db):
    banner("Employee List")
    emps = db.get_employees()
    print_table(emps, ['id', 'employee_code', 'name', 'department_name',
                        'designation', 'status', 'join_date'])


def cmd_employee_shift(db, employee_code, shift_name):
    emp = db.get_employee(employee_code=employee_code)
    if not emp:
        print(f"  ✗ Employee not found: {employee_code}")
        return

    shifts = db.get_shifts()
    shift  = next((s for s in shifts if s['name'].lower() == shift_name.lower()), None)
    if not shift:
        print(f"  ✗ Shift not found: {shift_name}")
        print("  Available:", ', '.join(s['name'] for s in shifts))
        return

    ok = db.assign_shift(emp['id'], shift['id'])
    if ok:
        print(f"  ✓ '{shift_name}' assigned to {emp['name']} from today")


# ── Shift commands ───────────────────────────────────────────────────────

def cmd_shift_list(db):
    banner("Shift Definitions")
    shifts = db.get_shifts()
    print_table(shifts, ['id', 'name', 'start_time', 'end_time',
                          'grace_late', 'grace_early_out', 'overtime_after',
                          'is_overnight', 'is_flexible', 'working_days'])


def cmd_shift_add(db):
    banner("Create New Shift")
    name    = input("  Shift name          : ").strip()
    start   = input("  Start time (HH:MM)  : ").strip()
    end     = input("  End time   (HH:MM)  : ").strip()
    grace_l = int(input("  Grace late (min) [15]: ").strip() or 15)
    grace_e = int(input("  Grace early out (min) [10]: ").strip() or 10)
    ot      = int(input("  Overtime after (min) [30]: ").strip() or 30)
    overnight= input("  Overnight shift? [y/N]: ").strip().lower() == 'y'
    flexible = input("  Flexible shift?   [y/N]: ").strip().lower() == 'y'
    days    = input("  Working days [Mon,Tue,Wed,Thu,Fri]: ").strip() or 'Mon,Tue,Wed,Thu,Fri'

    sid = db.add_shift(name, start, end, grace_l, grace_e, ot,
                       int(overnight), int(flexible), days)
    if sid:
        print(f"\n  ✓ Shift '{name}' created (id={sid})")


# ── Leave commands ───────────────────────────────────────────────────────

def cmd_leave_apply(db):
    banner("Apply Leave")
    emp_code = input("  Employee code: ").strip()
    emp = db.get_employee(employee_code=emp_code)
    if not emp:
        print(f"  ✗ Employee not found: {emp_code}")
        return

    types = db.get_leave_types()
    print("\n  Leave types:")
    for t in types:
        print(f"    [{t['id']}] {t['name']} (allowed: {t['days_allowed']} days/year)")

    lt_id  = int(input("  Leave type ID: ").strip())
    from_d = input("  From date (YYYY-MM-DD): ").strip()
    to_d   = input("  To date   (YYYY-MM-DD): ").strip()
    reason = input("  Reason (optional)     : ").strip() or None

    lid = db.apply_leave(emp['id'], lt_id, from_d, to_d, reason)
    if lid:
        print(f"\n  ✓ Leave applied (id={lid}) — status: pending")


def cmd_leave_approve(db, leave_id):
    ok = db.approve_leave(int(leave_id))
    if ok:
        print(f"  ✓ Leave {leave_id} approved")


def cmd_leave_list(db, employee_code=None):
    banner("Leave Requests")
    emp_id = None
    if employee_code:
        emp = db.get_employee(employee_code=employee_code)
        emp_id = emp['id'] if emp else None

    rows = db.get_leave_requests(employee_id=emp_id)
    print_table(rows, ['id', 'employee_name', 'leave_type_name',
                        'from_date', 'to_date', 'days', 'status', 'reason'])


# ── Attendance commands ──────────────────────────────────────────────────

def cmd_attendance_report(db, work_date):
    banner(f"Daily Attendance — {work_date}")
    rows = db.get_daily_report(work_date)
    print_table(rows, ['employee_code', 'name', 'department', 'shift',
                        'check_in', 'check_out', 'working_minutes',
                        'late_minutes', 'status'])


def cmd_attendance_monthly(db, year, month):
    banner(f"Monthly Report — {year}/{month:02d}")
    rows = db.get_monthly_report(year, month)
    print_table(rows, ['employee_code', 'name', 'department',
                        'present_days', 'absent_days', 'leave_days',
                        'late_days', 'total_minutes', 'overtime_minutes'])


def cmd_attendance_process(db, work_date):
    banner(f"Processing Attendance — {work_date}")
    proc = AttendanceProcessor(db)
    n = proc.process_date(work_date)
    proc.mark_absent(work_date)
    print(f"  ✓ Processed {n} employees for {work_date}")


def cmd_biometric_register(db):
    banner("Register Biometric Data")
    emp_code = input("  Employee code : ").strip()
    emp = db.get_employee(employee_code=emp_code)
    if not emp:
        print(f"  ✗ Employee not found: {emp_code}")
        return

    devices = db.get_devices()
    if not devices:
        print("  ✗ No devices in database. Add devices via config first.")
        return

    print("\n  Devices:")
    for d in devices:
        print(f"    [{d['id']}] {d['name']} ({d['serial_number']}) — {d['ip']}")
    device_sn = input("  Device serial number: ").strip()

    print("\n  Type: [1] fingerprint  [2] face  [3] card  [4] pin")
    t = input("  Choice [1]: ").strip() or '1'
    bio_type = {'1':'fingerprint','2':'face','3':'card','4':'pin'}.get(t, 'fingerprint')

    card_number = None
    pin         = None
    finger_idx  = 0

    if bio_type == 'card':
        card_number = input("  Card number: ").strip()
    elif bio_type == 'pin':
        pin = input("  PIN: ").strip()
    elif bio_type == 'fingerprint':
        finger_idx = int(input("  Finger index (0=right thumb … 9=left pinky) [0]: ").strip() or 0)

    ok = db.register_biometric(
        employee_id  = emp['id'],
        device_sn    = device_sn,
        bio_type     = bio_type,
        card_number  = card_number,
        pin          = pin,
        finger_index = finger_idx,
    )
    if ok:
        print(f"\n  ✓ {bio_type} registered for {emp['name']} on device {device_sn}")


def cmd_biometric_list(db, employee_code):
    banner(f"Biometrics — {employee_code}")
    emp = db.get_employee(employee_code=employee_code)
    if not emp:
        print(f"  ✗ Employee not found: {employee_code}")
        return
    rows = db.get_employee_biometrics(emp['id'])
    print_table(rows, ['id', 'type', 'device_sn', 'card_number', 'finger_index', 'enrolled_at'])


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Biometric Attendance Management CLI")
    sub = p.add_subparsers(dest='entity')

    # employee
    ep = sub.add_parser('employee')
    ea = ep.add_subparsers(dest='action')
    ea.add_parser('add')
    ea.add_parser('list')
    es = ea.add_parser('shift')
    es.add_argument('employee_code')
    es.add_argument('shift_name')

    # shift
    sp = sub.add_parser('shift')
    sa = sp.add_subparsers(dest='action')
    sa.add_parser('list')
    sa.add_parser('add')

    # leave
    lp = sub.add_parser('leave')
    la = lp.add_subparsers(dest='action')
    la.add_parser('apply')
    lap = la.add_parser('approve')
    lap.add_argument('leave_id')
    ll = la.add_parser('list')
    ll.add_argument('--employee', default=None)

    # attendance
    ap2 = sub.add_parser('attendance')
    aa  = ap2.add_subparsers(dest='action')
    ar  = aa.add_parser('report')
    ar.add_argument('--date', default=date.today().isoformat())
    am  = aa.add_parser('monthly')
    am.add_argument('--year',  type=int, default=date.today().year)
    am.add_argument('--month', type=int, default=date.today().month)
    apc = aa.add_parser('process')
    apc.add_argument('--date', default=date.today().isoformat())

    # biometric
    bp = sub.add_parser('biometric')
    ba = bp.add_subparsers(dest='action')
    ba.add_parser('register')
    bl = ba.add_parser('list')
    bl.add_argument('employee_code')

    args = p.parse_args()
    db   = get_db()

    if args.entity == 'employee':
        if args.action == 'add':        cmd_employee_add(db)
        elif args.action == 'list':     cmd_employee_list(db)
        elif args.action == 'shift':    cmd_employee_shift(db, args.employee_code, args.shift_name)
        else: ep.print_help()

    elif args.entity == 'shift':
        if args.action == 'list':       cmd_shift_list(db)
        elif args.action == 'add':      cmd_shift_add(db)
        else: sp.print_help()

    elif args.entity == 'leave':
        if args.action == 'apply':      cmd_leave_apply(db)
        elif args.action == 'approve':  cmd_leave_approve(db, args.leave_id)
        elif args.action == 'list':     cmd_leave_list(db, args.employee)
        else: lp.print_help()

    elif args.entity == 'attendance':
        if args.action == 'report':     cmd_attendance_report(db, args.date)
        elif args.action == 'monthly':  cmd_attendance_monthly(db, args.year, args.month)
        elif args.action == 'process':  cmd_attendance_process(db, args.date)
        else: ap2.print_help()

    elif args.entity == 'biometric':
        if args.action == 'register':   cmd_biometric_register(db)
        elif args.action == 'list':     cmd_biometric_list(db, args.employee_code)
        else: bp.print_help()

    else:
        p.print_help()


if __name__ == '__main__':
    main()
