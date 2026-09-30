"""
Permission catalog for owner-defined custom roles.

A CustomRole stores a list of permission codenames from PERMISSION_CATALOG.
At request time the effective set is resolved (see ``resolve_permissions``)
and attached to the request, where DRF permission classes
(``RequiresPermission``) and /auth/me/ can use it.

Built-in roles implicitly hold every permission scoped at their level or
below (OWNER ⊇ STAFF ⊇ TRAINER ⊇ MEMBER). Custom roles hold exactly the
codenames saved on them.

Base-level safety: a custom role's GymMembership.role is computed from its
permissions and is NEVER 'OWNER' — owner-only capabilities (roles, audit,
gym settings) stay reserved for real owners. Endpoints that expose an
owner-only capability are opened to custom roles only through
``RequiresPermission``.
"""

# scope: one of OWNER / STAFF / TRAINER / MEMBER.
# - STAFF-scoped permissions are the "front desk" capabilities.
# - TRAINER-scoped are coaching capabilities.
# - MEMBER-scoped are self-service capabilities.
# - OWNER-scoped capabilities can be GRANTED to a custom role (e.g. reports)
#   but assigning them never grants the OWNER base level — the endpoint must
#   opt in via RequiresPermission.
PERMISSION_CATALOG = {
    # Members
    'members.view':    {'label': 'View members', 'category': 'Members', 'scope': 'STAFF'},
    'members.manage':  {'label': 'Add / edit / deactivate members', 'category': 'Members', 'scope': 'STAFF'},
    # Memberships, plans, offers
    'memberships.view':   {'label': 'View memberships', 'category': 'Memberships', 'scope': 'STAFF'},
    'memberships.manage': {'label': 'Assign / cancel / freeze memberships', 'category': 'Memberships', 'scope': 'STAFF'},
    'plans.view':      {'label': 'View membership plans', 'category': 'Memberships', 'scope': 'STAFF'},
    'plans.manage':    {'label': 'Create / edit plans', 'category': 'Memberships', 'scope': 'STAFF'},
    'offers.view':     {'label': 'View offers & promo codes', 'category': 'Memberships', 'scope': 'STAFF'},
    'offers.manage':   {'label': 'Create / edit offers & promo codes', 'category': 'Memberships', 'scope': 'STAFF'},
    # Payments
    'payments.view':    {'label': 'View payments', 'category': 'Payments', 'scope': 'STAFF'},
    'payments.manage':  {'label': 'Record / edit payments', 'category': 'Payments', 'scope': 'STAFF'},
    'payments.summary': {'label': 'View payment summary & totals', 'category': 'Payments', 'scope': 'STAFF'},
    # Attendance
    'attendance.view':   {'label': 'View attendance', 'category': 'Attendance', 'scope': 'STAFF'},
    'attendance.manage': {'label': 'Mark / edit attendance', 'category': 'Attendance', 'scope': 'STAFF'},
    # Progress
    'progress.view':   {'label': 'View member progress', 'category': 'Progress', 'scope': 'TRAINER'},
    'progress.manage': {'label': 'Record member progress', 'category': 'Progress', 'scope': 'TRAINER'},
    # Workouts & diet (trainer-side)
    'workouts.view':   {'label': 'View workout plans', 'category': 'Workout & Diet', 'scope': 'TRAINER'},
    'workouts.manage': {'label': 'Create / assign workout plans', 'category': 'Workout & Diet', 'scope': 'TRAINER'},
    'diet.view':       {'label': 'View diet plans', 'category': 'Workout & Diet', 'scope': 'TRAINER'},
    'diet.manage':     {'label': 'Create / assign diet plans', 'category': 'Workout & Diet', 'scope': 'TRAINER'},
    # Trainer assignments
    'trainer-assignments.view':   {'label': 'View trainer assignments', 'category': 'Trainers', 'scope': 'STAFF'},
    'trainer-assignments.manage': {'label': 'Assign trainers to members', 'category': 'Trainers', 'scope': 'STAFF'},
    # Staff & trainers management
    'staff.view':    {'label': 'View staff list', 'category': 'Staff Management', 'scope': 'STAFF'},
    'staff.manage':  {'label': 'Add / edit / deactivate staff', 'category': 'Staff Management', 'scope': 'STAFF'},
    'trainers.view':   {'label': 'View trainer list', 'category': 'Staff Management', 'scope': 'STAFF'},
    'trainers.manage': {'label': 'Add / edit / deactivate trainers', 'category': 'Staff Management', 'scope': 'STAFF'},
    'leaves.view':   {'label': 'View leave requests', 'category': 'Staff Management', 'scope': 'STAFF'},
    'leaves.review': {'label': 'Approve / reject leave requests', 'category': 'Staff Management', 'scope': 'STAFF'},
    # Lockers & equipment
    'lockers.view':    {'label': 'View lockers', 'category': 'Facilities', 'scope': 'STAFF'},
    'lockers.manage':  {'label': 'Manage lockers & assignments', 'category': 'Facilities', 'scope': 'STAFF'},
    'equipment.view':    {'label': 'View equipment', 'category': 'Facilities', 'scope': 'STAFF'},
    'equipment.manage':  {'label': 'Manage equipment & maintenance', 'category': 'Facilities', 'scope': 'STAFF'},
    # Messaging
    'messages.use': {'label': 'Send & receive messages', 'category': 'Communication', 'scope': 'STAFF'},
    'notifications.broadcast': {'label': 'Send announcements / notifications', 'category': 'Communication', 'scope': 'STAFF'},
    # Insights & administration (grantable, but never confer the OWNER base level)
    'reports.view':  {'label': 'View reports & analytics', 'category': 'Administration', 'scope': 'OWNER'},
    'import.data':   {'label': 'Import data from Excel', 'category': 'Administration', 'scope': 'OWNER'},
    'trash.manage':  {'label': 'Restore / purge deleted records', 'category': 'Administration', 'scope': 'OWNER'},
    'audit.view':    {'label': 'View audit logs', 'category': 'Administration', 'scope': 'OWNER'},
    'impersonate':   {'label': 'View the app as another user', 'category': 'Administration', 'scope': 'OWNER'},
}

# Permissions that are exclusively meaningful for owners; a custom role may
# hold them but the matching endpoints enforce RequiresPermission explicitly.
OWNER_GRANTABLE = {code for code, meta in PERMISSION_CATALOG.items() if meta['scope'] == 'OWNER'}

TRAINER_SCOPED = {code for code, meta in PERMISSION_CATALOG.items() if meta['scope'] == 'TRAINER'}
MEMBER_SCOPED = {code for code, meta in PERMISSION_CATALOG.items() if meta['scope'] == 'MEMBER'}
STAFF_SCOPED = {code for code, meta in PERMISSION_CATALOG.items() if meta['scope'] == 'STAFF'}

VALID_CODES = set(PERMISSION_CATALOG.keys())


def catalog_grouped():
    """Catalog grouped by category — used by the roles UI."""
    grouped = {}
    for code, meta in PERMISSION_CATALOG.items():
        grouped.setdefault(meta['category'], []).append({
            'code': code,
            'label': meta['label'],
            'scope': meta['scope'],
        })
    return grouped


def level_for_permissions(codes):
    """
    Compute the built-in base level a custom role needs so existing
    role-based endpoint checks keep working.

    Never returns OWNER: owner-level endpoints require the built-in role;
    custom roles reach owner-only capabilities through RequiresPermission.
    """
    codes = set(codes or [])
    if codes & STAFF_SCOPED or codes & OWNER_GRANTABLE:
        return 'STAFF'
    if codes & TRAINER_SCOPED:
        return 'TRAINER'
    return 'MEMBER'


def builtin_permissions(role):
    """Effective permission set for a built-in role (superset chain)."""
    role = (role or '').upper()
    if role == 'OWNER':
        return set(VALID_CODES)
    if role == 'STAFF':
        return set(VALID_CODES) - OWNER_GRANTABLE
    if role == 'TRAINER':
        return TRAINER_SCOPED | MEMBER_SCOPED
    if role == 'MEMBER':
        return set(MEMBER_SCOPED) | {
            # Self-evident member capabilities kept explicit for clarity.
            'progress.view', 'progress.manage',
        }
    return set()


def resolve_permissions(role, custom_role_permissions=None):
    """Effective permission set for a gym membership."""
    if custom_role_permissions is not None:
        return {c for c in (custom_role_permissions or []) if c in VALID_CODES}
    return builtin_permissions(role)
