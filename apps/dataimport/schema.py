"""
Declarative column + row rules for the bulk workbook import.

Each Sheet subclass describes one worksheet of the uploaded workbook:

  • columns   — ordered headers (label, aliases, required flag)
  • parsers   — per-column cell parsers; every parser returns a typed value
  • identity  — the key that catches duplicate rows *inside* the file
  • existing  — returns a human reason to skip a row already in the database
  • insert    — creates the row (only called on a real, error-free commit)

Parsers and validators raise RowError(column, message); the importer turns
those into the per-row errors shown in the UI preview.

Sheet order matters (see SHEETS): a sheet is processed only after the sheets
it references — plans before memberships, people before anything linking to
them. While validating, rows this same file will create are registered on the
shared import context as "planned", so cross-references inside one workbook
validate correctly before a single row is written.
"""
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone as django_timezone

from apps.accounts.models import User
from apps.attendance.models import Attendance
from apps.equipment.models import Equipment
from apps.lockers.models import Locker, LockerAssignment
from apps.members.models import MemberProfile
from apps.memberships.models import Membership, MembershipPlan, Offer, PromoCode
from apps.payments.models import Payment
from apps.progress.models import ProgressEntry
from apps.staff.models import StaffProfile
from apps.trainers.models import TrainerMemberAssignment, TrainerProfile


# ─────────────────────────────────────────────────────────────────────────────
# Errors & cell helpers
# ─────────────────────────────────────────────────────────────────────────────

class RowError(Exception):
    """A single cell/row failed validation."""

    def __init__(self, column, message):
        super().__init__(f'{column}: {message}')
        self.column = column
        self.message = message


TRUE_VALUES = frozenset({'1', 'true', 't', 'yes', 'y', 'on'})
FALSE_VALUES = frozenset({'0', 'false', 'f', 'no', 'n', 'off'})
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')
EXCEL_EPOCH = datetime(1899, 12, 30)


def as_text(value):
    """Render any spreadsheet cell as a trimmed string."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime('%H:%M')
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def norm_header(value):
    """Normalize a header cell for matching: 'Price Paid (NPR)' -> 'pricepaidnpr'."""
    return re.sub(r'[^a-z0-9]+', '', as_text(value).lower())


def norm_choice(value):
    """Normalize a choice: 'Bank Transfer', 'bank-transfer' -> 'BANK_TRANSFER'."""
    return re.sub(r'[^A-Z0-9]+', '_', as_text(value).upper()).strip('_')


# ─────────────────────────────────────────────────────────────────────────────
# Cell parsers. Every parser has the signature parser(value, column_label) and
# either returns a typed value or raises RowError.
# ─────────────────────────────────────────────────────────────────────────────

def p_text(value, column):
    return as_text(value)


def p_email(value, column):
    text = as_text(value).lower()
    if text and not EMAIL_RE.match(text):
        raise RowError(column, f'"{text}" is not a valid email address.')
    return text


def p_int(default=None, minimum=None, maximum=None):
    def parse(value, column):
        text = as_text(value)
        if not text:
            return default
        cleaned = re.sub(r'[^0-9.\-]', '', text)
        try:
            number = Decimal(cleaned)
        except InvalidOperation:
            raise RowError(column, f'"{text}" is not a number.')
        if number != number.to_integral_value():
            raise RowError(column, f'"{text}" is not a whole number.')
        number = int(number)
        if minimum is not None and number < minimum:
            raise RowError(column, f'Must be {minimum} or more (got {number}).')
        if maximum is not None and number > maximum:
            raise RowError(column, f'Must be {maximum} or less (got {number}).')
        return number

    return parse


def p_decimal(default=None, minimum=None, maximum=None):
    def parse(value, column):
        text = as_text(value)
        if not text:
            return default
        cleaned = re.sub(r'[^0-9.\-]', '', text)
        try:
            number = Decimal(cleaned)
        except InvalidOperation:
            raise RowError(column, f'"{text}" is not a number.')
        if minimum is not None and number < minimum:
            raise RowError(column, f'Must be {minimum} or more (got {number}).')
        if maximum is not None and number > maximum:
            raise RowError(column, f'Must be {maximum} or less (got {number}).')
        return number

    return parse


_DATE_FORMATS = (
    '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d', '%m/%d/%Y',
    '%d %b %Y', '%d %B %Y', '%b %d, %Y', '%B %d, %Y',
)


def p_date(default=None):
    def parse(value, column):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = as_text(value)
        if not text:
            return default
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        message = f'"{text}" is not a date — use YYYY-MM-DD (e.g. 2026-01-31).'
        try:
            serial = float(text)
        except ValueError:
            raise RowError(column, message)
        if 1 <= serial <= 2958465:  # Excel day serial (1900-based w/ 1900 leap bug)
            return (EXCEL_EPOCH + timedelta(days=int(serial))).date()
        raise RowError(column, message)

    return parse


_TIME_FORMATS = ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p')


def p_time(default=None):
    def parse(value, column):
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, time):
            return value
        text = as_text(value)
        if not text:
            return default
        message = f'"{text}" is not a time — use HH:MM (e.g. 07:30 or 19:00).'
        for fmt in _TIME_FORMATS:
            candidate = text.upper() if '%p' in fmt else text
            try:
                return datetime.strptime(candidate, fmt).time()
            except ValueError:
                continue
        try:
            fraction = float(text)
        except ValueError:
            raise RowError(column, message)
        if 0 <= fraction < 1:  # Excel stores times as fractions of a day
            total_seconds = round(fraction * 86400) % 86400
            return (datetime.min + timedelta(seconds=total_seconds)).time()
        raise RowError(column, message)

    return parse


_DATETIME_FORMATS = (
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M',
    '%Y-%m-%d', '%d/%m/%Y %H:%M', '%d/%m/%Y %H:%M:%S', '%d-%m-%Y %H:%M',
)


def _as_aware(value):
    if settings.USE_TZ and django_timezone.is_naive(value):
        return django_timezone.make_aware(value, django_timezone.get_current_timezone())
    return value


def p_datetime(default=None):
    def parse(value, column):
        if isinstance(value, datetime):
            return _as_aware(value)
        if isinstance(value, date):
            return _as_aware(datetime.combine(value, time.min))
        text = as_text(value)
        if not text:
            return default
        for fmt in _DATETIME_FORMATS:
            try:
                return _as_aware(datetime.strptime(text, fmt))
            except ValueError:
                continue
        raise RowError(
            column,
            f'"{text}" is not a date/time — use YYYY-MM-DD or YYYY-MM-DD HH:MM.',
        )

    return parse


def p_bool(default=True):
    def parse(value, column):
        if isinstance(value, bool):
            return value
        text = as_text(value).lower()
        if not text:
            return default
        if text in TRUE_VALUES:
            return True
        if text in FALSE_VALUES:
            return False
        raise RowError(column, f'"{as_text(value)}" is not a yes/no value — use Yes or No.')

    return parse


def p_list(default=None):
    """Split a cell into a list: 'A; B, C' -> ['A', 'B', 'C']."""

    def parse(value, column):
        text = as_text(value)
        if not text:
            return list(default or [])
        items = [part.strip() for part in re.split(r'[;|\n]+', text)]
        return [part for part in items if part] or list(default or [])

    return parse


def p_choice(choices, default=None, extra=None):
    """Match a cell against model choices by value or display label.

    'Bank Transfer', 'bank-transfer' and the raw value 'BANK' all resolve,
    because both sides go through norm_choice().
    """
    lookup = {}
    for value, display in choices:
        lookup[norm_choice(value)] = value
        lookup[norm_choice(display)] = value
    for alias, value in (extra or {}).items():
        lookup[norm_choice(alias)] = value
    allowed = ', '.join(display for _, display in choices)

    def parse(value, column):
        text = as_text(value)
        if not text:
            if default is not None:
                return default
            raise RowError(column, f'This field is required. Allowed values: {allowed}.')
        hit = lookup.get(norm_choice(text))
        if hit is None:
            raise RowError(column, f'"{text}" is not valid. Allowed values: {allowed}.')
        return hit

    return parse


def count_passwordless_accounts(rows, ctx):
    """Created accounts that arrive without their own Password value.

    They either take ctx.default_password (reported as "using default") or
    end up with an unusable password until reset — reported separately.
    """
    return sum(1 for _, row in rows if not row.get('password'))


def _sync_locker_status(locker):
    """Keep Locker.status consistent after an assignment is written.

    Mirrors apps.lockers.views._sync_locker_status — importing another app's
    views module for eight lines would be worse than duplicating them.
    """
    if locker.status not in (Locker.LockerStatus.OCCUPIED, Locker.LockerStatus.AVAILABLE):
        return
    occupied = LockerAssignment.objects.filter(locker=locker, is_active=True).exists()
    new_status = (
        Locker.LockerStatus.OCCUPIED if occupied else Locker.LockerStatus.AVAILABLE
    )
    if locker.status != new_status:
        locker.status = new_status
        locker.save(update_fields=['status'])


# ─────────────────────────────────────────────────────────────────────────────
# Sheet framework
# ─────────────────────────────────────────────────────────────────────────────

class Column:
    def __init__(self, key, label, aliases=(), required=False):
        self.key = key
        self.label = label
        self.aliases = tuple(aliases)
        self.required = required
        self.header_keys = frozenset(
            [norm_header(label)] + [norm_header(alias) for alias in self.aliases]
        )


class Sheet:
    key = ''
    name = ''
    aliases = ()
    description = ''
    columns = ()
    parsers = {}
    example = {}

    @classmethod
    def header_map(cls):
        """normalized header cell -> column key (first definition wins)."""
        mapping = {}
        for column in cls.columns:
            for header_key in column.header_keys:
                mapping.setdefault(header_key, column.key)
        return mapping

    @classmethod
    def clean(cls, row_number, raw, ctx):
        """Parse + validate one row. Raises RowError on the first bad cell."""
        data = {}
        for column in cls.columns:
            value = raw.get(column.key)
            if column.required and as_text(value) == '':
                raise RowError(column.label, 'This field is required.')
            parser = cls.parsers.get(column.key, p_text)
            data[column.key] = parser(value, column.label)
        return data

    @classmethod
    def identity(cls, data):
        """Duplicate key inside the file, or None when rows can't collide."""
        return None

    @classmethod
    def existing(cls, data, ctx):
        """Reason to skip this row (it already exists), or None to create it."""
        return None

    @classmethod
    def insert(cls, data, ctx):
        """Create the row. Only called on a real, error-free commit."""
        raise NotImplementedError

    @classmethod
    def default_password_count(cls, rows, ctx):
        return 0

    # ── Shared helpers for the three user sheets ────────────────────────────

    @classmethod
    def claim_user(cls, data, ctx, role):
        """Register a user row on the context; rejects role clashes."""
        email = data['email']
        existing = ctx.users.get(email)
        if existing is not None and existing.role != role:
            raise RowError(
                'Email',
                f'"{email}" already exists as a {existing.get_role_display()} account.',
            )
        planned = ctx.planned.get(email)
        if planned is not None and planned != role:
            raise RowError(
                'Email',
                f'"{email}" is already being imported as a {planned} account in this file.',
            )
        ctx.planned.setdefault(email, role)

    @classmethod
    def existing_user(cls, data, ctx):
        if ctx.users.get(data['email']) is not None:
            return 'Account already exists'
        return None

    @classmethod
    def create_user(cls, data, ctx, role):
        password = data.get('password') or ctx.default_password
        user = User(
            email=data['email'],
            first_name=data['first_name'],
            middle_name=data.get('middle_name', ''),
            last_name=data['last_name'],
            phone=data.get('phone', ''),
            role=role,
            is_active=data.get('is_active', True),
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        ctx.users[user.email] = user
        return user


# ─────────────────────────────────────────────────────────────────────────────
# Shared choice tables (borrowed from the models so labels never drift)
# ─────────────────────────────────────────────────────────────────────────────

GENDER_CHOICES = MemberProfile.Gender.choices
GOAL_CHOICES = MemberProfile.FitnessGoal.choices
LEVEL_CHOICES = MemberProfile.FitnessLevel.choices
EXTRA_GENDER = {'PREFER NOT TO SAY': 'N', 'NOT SPECIFIED': ''}
EXTRA_STATUS = {'CANCELED': 'CANCELLED', 'CANCEL': 'CANCELLED'}
EXTRA_PAY_METHOD = {'E-SEWA': 'ESEWA', 'ESWA': 'ESEWA', 'E SEWA': 'ESEWA', 'NEPALI PAY': 'OTHER'}


# ─────────────────────────────────────────────────────────────────────────────
# Sheets — listed in import order in SHEETS at the bottom of this module.
# ─────────────────────────────────────────────────────────────────────────────

class MembershipPlansSheet(Sheet):
    key = 'plans'
    name = 'Membership Plans'
    aliases = ('Plans', 'Plan', 'Membership Plan')
    description = 'The plan catalogue (billing cycle, duration, price, features).'
    columns = (
        Column('name', 'Name', required=True),
        Column('description', 'Description'),
        Column('billing_cycle', 'Billing Cycle', aliases=('Cycle',)),
        Column('duration_days', 'Duration (Days)', aliases=('Duration', 'Days'), required=True),
        Column('price', 'Price (NPR)', aliases=('Price', 'Price (NPR)'), required=True),
        Column('features', 'Features', aliases=('Feature',)),
        Column('is_active', 'Is Active', aliases=('Active',)),
    )
    parsers = {
        'billing_cycle': p_choice(MembershipPlan.BillingCycle.choices, default='MONTHLY'),
        'duration_days': p_int(minimum=1),
        'price': p_decimal(minimum=0),
        'features': p_list(),
        'is_active': p_bool(default=True),
    }
    example = {
        'name': 'Annual Premium',
        'description': 'Full access for a year, best value',
        'billing_cycle': 'ANNUAL',
        'duration_days': '365',
        'price': '24000',
        'features': 'Personal locker; 2 guest passes/month',
        'is_active': 'Yes',
    }

    @classmethod
    def identity(cls, data):
        return data['name'].lower()

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.planned_plans.add(data['name'].lower())
        return data

    @classmethod
    def existing(cls, data, ctx):
        if ctx.plans.get(data['name'].lower()) is not None:
            return 'Plan already exists'
        return None

    @classmethod
    def insert(cls, data, ctx):
        plan = MembershipPlan.objects.create(
            name=data['name'],
            description=data['description'],
            billing_cycle=data['billing_cycle'],
            duration_days=data['duration_days'],
            price=data['price'],
            features=data['features'],
            is_active=data['is_active'],
        )
        ctx.plans[plan.name.lower()] = plan
        return plan


class MembersSheet(Sheet):
    key = 'members'
    name = 'Members'
    aliases = ('Member', 'Member List', 'Members List', 'Users')
    description = 'Gym members — creates the login account and the member profile.'
    columns = (
        Column('email', 'Email', required=True),
        Column('first_name', 'First Name', required=True),
        Column('last_name', 'Last Name', required=True),
        Column('middle_name', 'Middle Name'),
        Column('phone', 'Phone', aliases=('Phone Number', 'Mobile')),
        Column('password', 'Password', aliases=('Temp Password', 'Temporary Password')),
        Column('date_of_birth', 'Date Of Birth', aliases=('DOB', 'Birth Date')),
        Column('gender', 'Gender'),
        Column('address', 'Address'),
        Column('emergency_contact_name', 'Emergency Contact Name', aliases=('Emergency Name',)),
        Column('emergency_contact_phone', 'Emergency Contact Phone', aliases=('Emergency Phone',)),
        Column('height_cm', 'Height (cm)', aliases=('Height',)),
        Column('weight_kg', 'Weight (kg)', aliases=('Weight',)),
        Column('fitness_goal', 'Fitness Goal', aliases=('Goal',)),
        Column('fitness_level', 'Fitness Level', aliases=('Level',)),
        Column('medical_conditions', 'Medical Conditions', aliases=('Medical Notes',)),
        Column('notes', 'Notes'),
        Column('is_active', 'Is Active', aliases=('Active',)),
    )
    parsers = {
        'email': p_email,
        'date_of_birth': p_date(),
        'gender': p_choice(GENDER_CHOICES, default='', extra=EXTRA_GENDER),
        'height_cm': p_decimal(),
        'weight_kg': p_decimal(),
        'fitness_goal': p_choice(GOAL_CHOICES, default=''),
        'fitness_level': p_choice(LEVEL_CHOICES, default='BEGINNER'),
        'is_active': p_bool(default=True),
    }
    example = {
        'email': 'anita.sharma@example.com',
        'first_name': 'Anita',
        'last_name': 'Sharma',
        'middle_name': '',
        'phone': '9841234567',
        'password': '',
        'date_of_birth': '1996-04-12',
        'gender': 'Female',
        'address': 'Baluwatar, Kathmandu',
        'emergency_contact_name': 'Ramesh Sharma',
        'emergency_contact_phone': '9841765432',
        'height_cm': '165',
        'weight_kg': '58.5',
        'fitness_goal': 'Weight Loss',
        'fitness_level': 'Beginner',
        'medical_conditions': '',
        'notes': '',
        'is_active': 'Yes',
    }

    @classmethod
    def identity(cls, data):
        return data['email']

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        if data['password'] and len(data['password']) < 6:
            raise RowError('Password', 'Password must be at least 6 characters.')
        cls.claim_user(data, ctx, User.Role.MEMBER)
        return data

    @classmethod
    def existing(cls, data, ctx):
        return cls.existing_user(data, ctx)

    @classmethod
    def default_password_count(cls, rows, ctx):
        return count_passwordless_accounts(rows, ctx)

    @classmethod
    def insert(cls, data, ctx):
        user = cls.create_user(data, ctx, User.Role.MEMBER)
        profile = MemberProfile.objects.get(user=user)
        profile.date_of_birth = data['date_of_birth']
        profile.gender = data['gender']
        profile.address = data['address']
        profile.emergency_contact_name = data['emergency_contact_name']
        profile.emergency_contact_phone = data['emergency_contact_phone']
        profile.height_cm = data['height_cm']
        profile.weight_kg = data['weight_kg']
        profile.fitness_goal = data['fitness_goal']
        profile.fitness_level = data['fitness_level']
        profile.medical_conditions = data['medical_conditions']
        profile.notes = data['notes']
        profile.save()


class StaffSheet(Sheet):
    key = 'staff'
    name = 'Staff'
    aliases=('Staff List', 'Employees')
    description = 'Staff accounts (receptionist, gym keeper, trainer) with profiles.'
    columns = (
        Column('email', 'Email', required=True),
        Column('first_name', 'First Name', required=True),
        Column('last_name', 'Last Name', required=True),
        Column('middle_name', 'Middle Name'),
        Column('phone', 'Phone', aliases=('Phone Number', 'Mobile')),
        Column('password', 'Password', aliases=('Temp Password',)),
        Column('staff_role', 'Staff Role', aliases=('Role', 'Position')),
        Column('joined_date', 'Joined Date', aliases=('Join Date', 'Date Of Joining')),
        Column('salary', 'Salary (NPR)', aliases=('Salary',)),
        Column('date_of_birth', 'Date Of Birth', aliases=('DOB',)),
        Column('gender', 'Gender'),
        Column('marital_status', 'Marital Status'),
        Column('nationality', 'Nationality'),
        Column('notes', 'Notes'),
        Column('is_active', 'Is Active', aliases=('Active',)),
    )
    parsers = {
        'email': p_email,
        'staff_role': p_choice(StaffProfile.Role.choices, default='RECEPTIONIST'),
        'joined_date': p_date(),
        'salary': p_decimal(minimum=0),
        'date_of_birth': p_date(),
        'gender': p_choice(GENDER_CHOICES, default='', extra=EXTRA_GENDER),
        'is_active': p_bool(default=True),
    }
    example = {
        'email': 'reception@fitcore.com',
        'first_name': 'Sita',
        'last_name': 'Adhikari',
        'middle_name': '',
        'phone': '9851001122',
        'password': '',
        'staff_role': 'RECEPTIONIST',
        'joined_date': '2025-01-15',
        'salary': '32000',
        'date_of_birth': '1994-09-02',
        'gender': 'Female',
        'marital_status': 'Single',
        'nationality': 'Nepali',
        'notes': '',
        'is_active': 'Yes',
    }

    @classmethod
    def identity(cls, data):
        return data['email']

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        if data['password'] and len(data['password']) < 6:
            raise RowError('Password', 'Password must be at least 6 characters.')
        cls.claim_user(data, ctx, User.Role.STAFF)
        return data

    @classmethod
    def existing(cls, data, ctx):
        return cls.existing_user(data, ctx)

    @classmethod
    def default_password_count(cls, rows, ctx):
        return count_passwordless_accounts(rows, ctx)

    @classmethod
    def insert(cls, data, ctx):
        user = cls.create_user(data, ctx, User.Role.STAFF)
        StaffProfile.objects.create(
            user=user,
            role=data['staff_role'],
            joined_date=data['joined_date'],
            salary=data['salary'],
            date_of_birth=data['date_of_birth'],
            gender=data['gender'],
            marital_status=data['marital_status'],
            nationality=data['nationality'],
            notes=data['notes'],
        )


class TrainersSheet(Sheet):
    key = 'trainers'
    name = 'Trainers'
    aliases=('Trainer', 'Trainer List', 'Coaches')
    description = 'Trainer accounts with specializations, experience and bio.'
    columns = (
        Column('email', 'Email', required=True),
        Column('first_name', 'First Name', required=True),
        Column('last_name', 'Last Name', required=True),
        Column('middle_name', 'Middle Name'),
        Column('phone', 'Phone', aliases=('Phone Number', 'Mobile')),
        Column('password', 'Password', aliases=('Temp Password',)),
        Column('specializations', 'Specializations', aliases=('Specialization', 'Skills')),
        Column('experience_years', 'Experience (Years)', aliases=('Experience', 'Years Of Experience')),
        Column('bio', 'Bio', aliases=('About',)),
        Column('joined_date', 'Joined Date', aliases=('Join Date',)),
        Column('salary', 'Salary (NPR)', aliases=('Salary',)),
        Column('is_available', 'Is Available', aliases=('Available',)),
        Column('is_active', 'Is Active', aliases=('Active',)),
    )
    parsers = {
        'email': p_email,
        'specializations': p_list(),
        'experience_years': p_int(default=0, minimum=0),
        'joined_date': p_date(),
        'salary': p_decimal(minimum=0),
        'is_available': p_bool(default=True),
        'is_active': p_bool(default=True),
    }
    example = {
        'email': 'coach.ram@fitcore.com',
        'first_name': 'Ram',
        'last_name': 'Thapa',
        'middle_name': '',
        'phone': '9803334455',
        'password': '',
        'specializations': 'Strength Training; Mobility',
        'experience_years': '6',
        'bio': 'Powerlifting coach, NASM certified.',
        'joined_date': '2024-06-01',
        'salary': '45000',
        'is_available': 'Yes',
        'is_active': 'Yes',
    }

    @classmethod
    def identity(cls, data):
        return data['email']

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        if data['password'] and len(data['password']) < 6:
            raise RowError('Password', 'Password must be at least 6 characters.')
        cls.claim_user(data, ctx, User.Role.TRAINER)
        return data

    @classmethod
    def existing(cls, data, ctx):
        return cls.existing_user(data, ctx)

    @classmethod
    def default_password_count(cls, rows, ctx):
        return count_passwordless_accounts(rows, ctx)

    @classmethod
    def insert(cls, data, ctx):
        user = cls.create_user(data, ctx, User.Role.TRAINER)
        TrainerProfile.objects.create(
            user=user,
            specializations=data['specializations'],
            experience_years=data['experience_years'],
            bio=data['bio'],
            joined_date=data['joined_date'],
            salary=data['salary'],
            is_available=data['is_available'],
        )


class OffersSheet(Sheet):
    key = 'offers'
    name = 'Offers'
    aliases=('Offer', 'Discounts', 'Discount Offers')
    description = 'Percentage or fixed-amount discount offers with validity windows.'
    columns = (
        Column('name', 'Name', aliases=('Offer Name',), required=True),
        Column('description', 'Description'),
        Column('discount_type', 'Discount Type', aliases=('Type',)),
        Column('discount_value', 'Discount Value', aliases=('Value', 'Discount'), required=True),
        Column('applicability', 'Applicability', aliases=('Applies To',)),
        Column('plans', 'Plans', aliases=('Plan Names', 'Plan')),
        Column('max_uses', 'Max Uses', aliases=('Max Total Uses',)),
        Column('max_uses_per_member', 'Max Uses Per Member'),
        Column('valid_from', 'Valid From', aliases=('Starts', 'Start Date'), required=True),
        Column('valid_until', 'Valid Until', aliases=('Ends', 'End Date'), required=True),
        Column('is_active', 'Is Active', aliases=('Active',)),
    )
    parsers = {
        'discount_type': p_choice(Offer.DiscountType.choices, default='PERCENTAGE'),
        'discount_value': p_decimal(minimum=0),
        'applicability': p_choice(Offer.Applicability.choices, default='ALL_PLANS'),
        'plans': p_list(),
        'max_uses': p_int(minimum=1),
        'max_uses_per_member': p_int(default=1, minimum=1),
        'valid_from': p_datetime(),
        'valid_until': p_datetime(),
        'is_active': p_bool(default=True),
    }
    example = {
        'name': 'Dashain Sale',
        'description': '20% off all annual plans',
        'discount_type': 'PERCENTAGE',
        'discount_value': '20',
        'applicability': 'ALL_PLANS',
        'plans': '',
        'max_uses': '100',
        'max_uses_per_member': '1',
        'valid_from': '2026-10-01 00:00',
        'valid_until': '2026-10-15 23:59',
        'is_active': 'Yes',
    }

    @classmethod
    def identity(cls, data):
        return data['name'].lower()

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        if data['valid_until'] and data['valid_from'] and data['valid_until'] <= data['valid_from']:
            raise RowError('Valid Until', 'Valid-until must be after valid-from.')
        for plan_name in data['plans']:
            ctx.resolve_plan(plan_name, 'Plans')
        ctx.planned_offers.add(data['name'].lower())
        return data

    @classmethod
    def existing(cls, data, ctx):
        if ctx.offers.get(data['name'].lower()) is not None:
            return 'Offer already exists'
        return None

    @classmethod
    def insert(cls, data, ctx):
        offer = Offer.objects.create(
            name=data['name'],
            description=data['description'],
            discount_type=data['discount_type'],
            discount_value=data['discount_value'],
            applicability=data['applicability'],
            max_uses=data['max_uses'],
            max_uses_per_member=data['max_uses_per_member'],
            valid_from=data['valid_from'],
            valid_until=data['valid_until'],
            is_active=data['is_active'],
        )
        if data['plans']:
            offer.plans.set([ctx.require_plan(name, 'Plans') for name in data['plans']])
        ctx.offers[offer.name.lower()] = offer
        return offer


class PromoCodesSheet(Sheet):
    key = 'promo_codes'
    name = 'Promo Codes'
    aliases=('Promo Code', 'PromoCodes', 'Codes')
    description = 'Redemption codes, each linked to an offer from the Offers sheet.'
    columns = (
        Column('code', 'Code', aliases=('Promo Code',), required=True),
        Column('offer_name', 'Offer Name', aliases=('Offer',), required=True),
        Column('status', 'Status'),
        Column('max_uses', 'Max Uses'),
        Column('used_count', 'Used Count', aliases=('Times Used',)),
        Column('valid_from', 'Valid From', aliases=('Starts', 'Start Date'), required=True),
        Column('valid_until', 'Valid Until', aliases=('Ends', 'End Date'), required=True),
    )
    parsers = {
        'status': p_choice(PromoCode.Status.choices, default='ACTIVE'),
        'max_uses': p_int(default=1, minimum=1),
        'used_count': p_int(default=0, minimum=0),
        'valid_from': p_datetime(),
        'valid_until': p_datetime(),
    }
    example = {
        'code': 'DASHAIN20',
        'offer_name': 'Dashain Sale',
        'status': 'ACTIVE',
        'max_uses': '50',
        'used_count': '0',
        'valid_from': '2026-10-01 00:00',
        'valid_until': '2026-10-15 23:59',
    }

    @classmethod
    def identity(cls, data):
        return data['code'].upper()

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.resolve_offer(data['offer_name'], 'Offer Name')
        if data['valid_until'] and data['valid_from'] and data['valid_until'] <= data['valid_from']:
            raise RowError('Valid Until', 'Valid-until must be after valid-from.')
        return data

    @classmethod
    def existing(cls, data, ctx):
        if PromoCode.objects.filter(code__iexact=data['code']).exists():
            return 'Promo code already exists'
        return None

    @classmethod
    def insert(cls, data, ctx):
        return PromoCode.objects.create(
            code=data['code'].upper(),
            offer=ctx.require_offer(data['offer_name'], 'Offer Name'),
            status=data['status'],
            max_uses=data['max_uses'],
            used_count=data['used_count'],
            valid_from=data['valid_from'],
            valid_until=data['valid_until'],
            created_by=ctx.actor,
        )


class MembershipsSheet(Sheet):
    key = 'memberships'
    name = 'Memberships'
    aliases=('Membership', 'Memberships List')
    description = 'Members linked to plans with start/end dates and status.'
    columns = (
        Column('member_email', 'Member Email', aliases=('Email', 'Member'), required=True),
        Column('plan_name', 'Plan Name', aliases=('Plan', 'Membership Plan'), required=True),
        Column('status', 'Status'),
        Column('start_date', 'Start Date', aliases=('Starts', 'Started'), required=True),
        Column('end_date', 'End Date', aliases=('Ends', 'Expires'), required=True),
        Column('price_paid', 'Price Paid (NPR)', aliases=('Price Paid', 'Amount Paid'), required=True),
        Column('freeze_start', 'Freeze Start'),
        Column('freeze_end', 'Freeze End'),
        Column('freeze_reason', 'Freeze Reason'),
        Column('notes', 'Notes'),
    )
    parsers = {
        'status': p_choice(Membership.Status.choices, default='PENDING', extra=EXTRA_STATUS),
        'start_date': p_date(),
        'end_date': p_date(),
        'price_paid': p_decimal(minimum=0),
        'freeze_start': p_date(),
        'freeze_end': p_date(),
    }
    example = {
        'member_email': 'anita.sharma@example.com',
        'plan_name': 'Annual Premium',
        'status': 'ACTIVE',
        'start_date': '2026-01-15',
        'end_date': '2027-01-14',
        'price_paid': '22000',
        'freeze_start': '',
        'freeze_end': '',
        'freeze_reason': '',
        'notes': 'Renewed from cash counter',
    }

    @classmethod
    def identity(cls, data):
        return (data['member_email'], data['plan_name'].lower(), data['start_date'])

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.resolve_user(data['member_email'], 'Member Email', role=User.Role.MEMBER)
        ctx.resolve_plan(data['plan_name'], 'Plan Name')
        if data['end_date'] < data['start_date']:
            raise RowError('End Date', 'End date is before the start date.')
        if data['freeze_start'] and data['freeze_end'] and data['freeze_end'] < data['freeze_start']:
            raise RowError('Freeze End', 'Freeze end is before the freeze start.')
        ctx.planned_memberships.add(
            (data['member_email'], data['plan_name'].lower())
        )
        return data

    @classmethod
    def existing(cls, data, ctx):
        user = ctx.users.get(data['member_email'])
        plan = ctx.plans.get(data['plan_name'].lower())
        if user is None or plan is None:
            return None  # this file creates them — nothing to collide with
        if Membership.objects.filter(
            member=user, plan=plan, start_date=data['start_date']
        ).exists():
            return 'Membership already exists'
        return None

    @classmethod
    def insert(cls, data, ctx):
        membership = Membership.objects.create(
            member=ctx.require_user(data['member_email'], 'Member Email', role=User.Role.MEMBER),
            plan=ctx.require_plan(data['plan_name'], 'Plan Name'),
            status=data['status'],
            start_date=data['start_date'],
            end_date=data['end_date'],
            price_paid=data['price_paid'],
            freeze_start=data['freeze_start'],
            freeze_end=data['freeze_end'],
            freeze_reason=data['freeze_reason'],
            notes=data['notes'],
        )
        ctx.memberships[(data['member_email'], data['plan_name'].lower())] = membership
        return membership


class PaymentsSheet(Sheet):
    key = 'payments'
    name = 'Payments'
    aliases=('Payment', 'Revenue', 'Transactions')
    description = 'Payment transactions; the received amount is recalculated on save.'
    columns = (
        Column('receipt_number', 'Receipt Number', aliases=('Receipt No.', 'Receipt No', 'Receipt #'), required=True),
        Column('member_email', 'Member Email', aliases=('Email', 'Member'), required=True),
        Column('payment_for', 'Payment For', aliases=('For',)),
        Column('amount', 'Amount (NPR)', aliases=('Amount',), required=True),
        Column('discount', 'Discount (NPR)', aliases=('Discount',)),
        Column('payment_method', 'Method', aliases=('Payment Method',)),
        Column('status', 'Status'),
        Column('transaction_id', 'Transaction ID', aliases=('Transaction Id', 'Txn ID')),
        Column('paid_at', 'Paid At', aliases=('Payment Date', 'Date')),
        Column('plan_name', 'Plan Name', aliases=('Plan', 'Membership Plan')),
        Column('collected_by', 'Collected By', aliases=('Collected By Email', 'Staff Email')),
        Column('notes', 'Notes'),
    )
    parsers = {
        'payment_for': p_choice(Payment.PaymentFor.choices, default='MEMBERSHIP'),
        'amount': p_decimal(minimum=Decimal('0.01')),
        'discount': p_decimal(default=Decimal('0'), minimum=0),
        'payment_method': p_choice(Payment.PaymentMethod.choices, default='CASH', extra=EXTRA_PAY_METHOD),
        'status': p_choice(Payment.PaymentStatus.choices, default='PAID', extra=EXTRA_STATUS),
        'paid_at': p_datetime(),
        'collected_by': p_email,
    }
    example = {
        'receipt_number': 'RCP-1001',
        'member_email': 'anita.sharma@example.com',
        'payment_for': 'MEMBERSHIP',
        'amount': '24000',
        'discount': '2000',
        'payment_method': 'CASH',
        'status': 'PAID',
        'transaction_id': '',
        'paid_at': '2026-01-15 10:30',
        'plan_name': 'Annual Premium',
        'collected_by': 'reception@fitcore.com',
        'notes': '',
    }

    @classmethod
    def identity(cls, data):
        return data['receipt_number'].lower()

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.resolve_user(data['member_email'], 'Member Email', role=User.Role.MEMBER)
        if data['discount'] > data['amount']:
            raise RowError('Discount (NPR)', 'Discount cannot be more than the amount.')
        if data['plan_name']:
            if not ctx.membership_ref_valid(data['member_email'], data['plan_name']):
                raise RowError(
                    'Plan Name',
                    f'No "{data["plan_name"]}" membership found for {data["member_email"]}.',
                )
        if data['collected_by']:
            ctx.resolve_user(data['collected_by'], 'Collected By')
        return data

    @classmethod
    def existing(cls, data, ctx):
        if Payment.objects.filter(receipt_number__iexact=data['receipt_number']).exists():
            return 'Receipt number already exists'
        return None

    @classmethod
    def insert(cls, data, ctx):
        membership = None
        if data['plan_name']:
            membership = ctx.require_membership(
                data['member_email'], data['plan_name'], 'Plan Name'
            )
        collected_by = None
        if data['collected_by']:
            collected_by = ctx.require_user(data['collected_by'], 'Collected By')
        return Payment.objects.create(
            member=ctx.require_user(data['member_email'], 'Member Email', role=User.Role.MEMBER),
            membership=membership,
            payment_for=data['payment_for'],
            amount=data['amount'],
            discount=data['discount'],
            payment_method=data['payment_method'],
            status=data['status'],
            transaction_id=data['transaction_id'],
            receipt_number=data['receipt_number'],
            paid_at=data['paid_at'],
            collected_by=collected_by or ctx.actor,
            notes=data['notes'],
        )


class AttendanceSheet(Sheet):
    key = 'attendance'
    name = 'Attendance'
    aliases=('Attendances', 'Check-ins', 'Checkins')
    description = 'Daily attendance; the Type column is derived from the account when blank.'
    columns = (
        Column('email', 'Email', aliases=('User Email', 'Member Email'), required=True),
        Column('date', 'Date', required=True),
        Column('attendance_type', 'Type', aliases=('Attendance Type',)),
        Column('status', 'Status'),
        Column('check_in', 'Check In', aliases=('Check In Time', 'In')),
        Column('check_out', 'Check Out', aliases=('Check Out Time', 'Out')),
        Column('marked_by', 'Marked By', aliases=('Marked By Email',)),
        Column('notes', 'Notes'),
    )
    parsers = {
        'date': p_date(),
        # '' means "work it out from the account's role" (done in clean()).
        'attendance_type': p_choice(Attendance.AttendanceType.choices, default=''),
        'status': p_choice(Attendance.Status.choices, default='PRESENT'),
        'check_in': p_time(),
        'check_out': p_time(),
        'marked_by': p_email,
    }
    example = {
        'email': 'anita.sharma@example.com',
        'date': '2026-01-15',
        'attendance_type': '',
        'status': 'PRESENT',
        'check_in': '07:30',
        'check_out': '09:00',
        'marked_by': 'reception@fitcore.com',
        'notes': '',
    }

    @classmethod
    def identity(cls, data):
        return (data['email'], data['date'])

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        user = ctx.resolve_user(data['email'], 'Email')
        role = user.role if user is not None else ctx.planned.get(data['email'])
        if data['attendance_type']:
            if role and role != data['attendance_type']:
                raise RowError(
                    'Type',
                    f'"{data["email"]}" is a {role} account, but this row says {data["attendance_type"]}.',
                )
        else:
            if role in (User.Role.MEMBER, User.Role.STAFF, User.Role.TRAINER):
                data['attendance_type'] = role
            else:
                raise RowError(
                    'Type',
                    'Could not work out the type for this account — fill in the Type column '
                    '(MEMBER, STAFF or TRAINER).',
                )
        if data['check_in'] and data['check_out'] and data['check_out'] < data['check_in']:
            raise RowError('Check Out', 'Check-out is before check-in.')
        if data['marked_by']:
            ctx.resolve_user(data['marked_by'], 'Marked By')
        return data

    @classmethod
    def existing(cls, data, ctx):
        user = ctx.users.get(data['email'])
        if user is None:
            return None  # brand-new account, no attendance possible yet
        if Attendance.objects.filter(user=user, date=data['date']).exists():
            return 'Attendance already recorded for this date'
        return None

    @classmethod
    def insert(cls, data, ctx):
        marked_by = ctx.require_user(data['marked_by'], 'Marked By') if data['marked_by'] else ctx.actor
        return Attendance.objects.create(
            user=ctx.require_user(data['email'], 'Email'),
            attendance_type=data['attendance_type'],
            date=data['date'],
            status=data['status'],
            check_in=data['check_in'],
            check_out=data['check_out'],
            marked_by=marked_by,
            notes=data['notes'],
        )


class EquipmentSheet(Sheet):
    key = 'equipment'
    name = 'Equipment'
    aliases=('Equipments', 'Machines', 'Inventory')
    description = 'Equipment inventory; serial number (or name+model+location) de-duplicates.'
    columns = (
        Column('name', 'Name', aliases=('Equipment', 'Equipment Name'), required=True),
        Column('category', 'Category'),
        Column('brand', 'Brand'),
        Column('model_number', 'Model', aliases=('Model Number',)),
        Column('serial_number', 'Serial Number', aliases=('Serial', 'S/N')),
        Column('quantity', 'Quantity', aliases=('Qty',)),
        Column('purchase_date', 'Purchase Date', aliases=('Purchased On',)),
        Column('purchase_price', 'Purchase Price (NPR)', aliases=('Purchase Price', 'Price')),
        Column('condition', 'Condition'),
        Column('location', 'Location'),
        Column('notes', 'Notes'),
    )
    parsers = {
        'quantity': p_int(default=1, minimum=1),
        'purchase_date': p_date(),
        'purchase_price': p_decimal(minimum=0),
        'condition': p_choice(Equipment.Condition.choices, default='GOOD'),
    }
    example = {
        'name': 'Treadmill',
        'category': 'Cardio',
        'brand': 'Life Fitness',
        'model_number': 'T5',
        'serial_number': 'LF-T5-0001',
        'quantity': '2',
        'purchase_date': '2025-03-10',
        'purchase_price': '350000',
        'condition': 'GOOD',
        'location': 'Cardio Floor',
        'notes': '',
    }

    @classmethod
    def identity(cls, data):
        serial = data['serial_number'].lower()
        if serial:
            return ('serial', serial)
        return ('combo', data['name'].lower(), data['model_number'].lower(), data['location'].lower())

    @classmethod
    def existing(cls, data, ctx):
        serial = data['serial_number'].strip()
        if serial:
            if Equipment.objects.filter(serial_number__iexact=serial).exists():
                return 'Equipment with this serial number already exists'
        elif Equipment.objects.filter(
            name__iexact=data['name'],
            model_number__iexact=data['model_number'],
            location__iexact=data['location'],
        ).exists():
            return 'Matching equipment already exists'
        return None

    @classmethod
    def insert(cls, data, ctx):
        return Equipment.objects.create(
            name=data['name'],
            category=data['category'],
            brand=data['brand'],
            model_number=data['model_number'],
            serial_number=data['serial_number'] or None,
            quantity=data['quantity'],
            purchase_date=data['purchase_date'],
            purchase_price=data['purchase_price'],
            condition=data['condition'],
            location=data['location'],
            notes=data['notes'],
        )


class LockersSheet(Sheet):
    key = 'lockers'
    name = 'Lockers'
    aliases=('Locker', 'Locker List')
    description = 'Physical lockers (number, location, status, monthly fee).'
    columns = (
        Column('locker_number', 'Locker Number', aliases=('Number', 'Locker'), required=True),
        Column('location', 'Location'),
        Column('status', 'Status'),
        Column('monthly_fee', 'Monthly Fee (NPR)', aliases=('Monthly Fee', 'Fee')),
        Column('notes', 'Notes'),
    )
    parsers = {
        'status': p_choice(
            Locker.LockerStatus.choices,
            default='AVAILABLE',
            extra={'MAINTENANCE': 'MAINTENANCE', 'UNDER MAINTENANCE': 'MAINTENANCE'},
        ),
        'monthly_fee': p_decimal(default=Decimal('0'), minimum=0),
    }
    example = {
        'locker_number': 'A-01',
        'location': "Men's Block A",
        'status': 'AVAILABLE',
        'monthly_fee': '500',
        'notes': '',
    }

    @classmethod
    def identity(cls, data):
        return data['locker_number'].lower()

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.planned_lockers.add(data['locker_number'].lower())
        return data

    @classmethod
    def existing(cls, data, ctx):
        if ctx.lockers.get(data['locker_number'].lower()) is not None:
            return 'Locker already exists'
        return None

    @classmethod
    def insert(cls, data, ctx):
        locker = Locker.objects.create(
            locker_number=data['locker_number'],
            location=data['location'],
            status=data['status'],
            monthly_fee=data['monthly_fee'],
            notes=data['notes'],
        )
        ctx.lockers[locker.locker_number.lower()] = locker
        return locker


class LockerAssignmentsSheet(Sheet):
    key = 'locker_assignments'
    name = 'Locker Assignments'
    aliases=('Locker Assignment', 'LockerRentals', 'Locker Rentals')
    description = 'Which member rents which locker, and for how long.'
    columns = (
        Column('locker_number', 'Locker Number', aliases=('Number', 'Locker'), required=True),
        Column('member_email', 'Member Email', aliases=('Email', 'Member'), required=True),
        Column('start_date', 'Start Date', aliases=('Starts',), required=True),
        Column('end_date', 'End Date', aliases=('Ends',)),
        Column('is_active', 'Is Active', aliases=('Active',)),
    )
    parsers = {
        'start_date': p_date(),
        'end_date': p_date(),
        'is_active': p_bool(default=True),
    }
    example = {
        'locker_number': 'A-01',
        'member_email': 'anita.sharma@example.com',
        'start_date': '2026-01-15',
        'end_date': '',
        'is_active': 'Yes',
    }

    @classmethod
    def identity(cls, data):
        return (data['locker_number'].lower(), data['member_email'], data['start_date'])

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.resolve_locker(data['locker_number'], 'Locker Number')
        ctx.resolve_user(data['member_email'], 'Member Email', role=User.Role.MEMBER)
        if data['end_date'] and data['end_date'] < data['start_date']:
            raise RowError('End Date', 'End date is before the start date.')
        if data['is_active']:
            number = data['locker_number'].lower()
            email = data['member_email']
            if number in ctx.active_lockers:
                raise RowError(
                    'Locker Number',
                    f'Locker {data["locker_number"]} already has an active row earlier in this sheet.',
                )
            if email in ctx.active_member_lockers:
                raise RowError(
                    'Member Email',
                    f'{email} already has an active locker row earlier in this sheet.',
                )
            ctx.active_lockers.add(number)
            ctx.active_member_lockers.add(email)
        return data

    @classmethod
    def existing(cls, data, ctx):
        locker = ctx.lockers.get(data['locker_number'].lower())
        member = ctx.users.get(data['member_email'])
        # Each side is checked on its own: a brand-new member can still clash
        # with a locker that is already taken, and vice versa.
        if locker is not None and member is not None:
            if LockerAssignment.objects.filter(
                locker=locker, member=member, start_date=data['start_date']
            ).exists():
                return 'Assignment already exists'
        if data['is_active'] and locker is not None:
            if LockerAssignment.objects.filter(locker=locker, is_active=True).exists():
                raise RowError(
                    'Locker Number',
                    f'Locker {data["locker_number"]} already has an active assignment.',
                )
        if data['is_active'] and member is not None:
            if LockerAssignment.objects.filter(member=member, is_active=True).exists():
                raise RowError(
                    'Member Email',
                    f'{data["member_email"]} already has an active locker assignment.',
                )
        return None

    @classmethod
    def insert(cls, data, ctx):
        locker = ctx.require_locker(data['locker_number'], 'Locker Number')
        member = ctx.require_user(data['member_email'], 'Member Email', role=User.Role.MEMBER)
        assignment = LockerAssignment.objects.create(
            locker=locker,
            member=member,
            start_date=data['start_date'],
            end_date=data['end_date'],
            is_active=data['is_active'],
            assigned_by=ctx.actor,
        )
        _sync_locker_status(locker)
        return assignment


class TrainerAssignmentsSheet(Sheet):
    key = 'trainer_assignments'
    name = 'Trainer Assignments'
    aliases=('Trainer Assignment', 'Trainer Members', 'Assignments')
    description = 'Trainer → member assignments (a member has one active trainer).'
    columns = (
        Column('trainer_email', 'Trainer Email', aliases=('Trainer', 'Email'), required=True),
        Column('member_email', 'Member Email', aliases=('Member', 'Member Email'), required=True),
        Column('assigned_date', 'Assigned Date', aliases=('Assigned On',)),
        Column('end_date', 'End Date', aliases=('Ends',)),
        Column('is_active', 'Is Active', aliases=('Active',)),
        Column('notes', 'Notes'),
    )
    parsers = {
        'assigned_date': p_date(),
        'end_date': p_date(),
        'is_active': p_bool(default=True),
    }
    example = {
        'trainer_email': 'coach.ram@fitcore.com',
        'member_email': 'anita.sharma@example.com',
        'assigned_date': '2026-01-15',
        'end_date': '',
        'is_active': 'Yes',
        'notes': 'Strength block',
    }

    @classmethod
    def identity(cls, data):
        return (data['trainer_email'], data['member_email'], data['assigned_date'])

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.resolve_user(data['trainer_email'], 'Trainer Email', role=User.Role.TRAINER)
        ctx.resolve_user(data['member_email'], 'Member Email', role=User.Role.MEMBER)
        if data['end_date'] and data['assigned_date'] and data['end_date'] < data['assigned_date']:
            raise RowError('End Date', 'End date is before the assigned date.')
        if data['is_active']:
            if data['member_email'] in ctx.active_trainee_members:
                raise RowError(
                    'Member Email',
                    f'{data["member_email"]} already has an active trainer row earlier in this sheet.',
                )
            ctx.active_trainee_members.add(data['member_email'])
        return data

    @classmethod
    def existing(cls, data, ctx):
        trainer = ctx.users.get(data['trainer_email'])
        member = ctx.users.get(data['member_email'])
        # Same-pair duplicates need both accounts; the "one active trainer per
        # member" rule only needs the member, who may be new to this file.
        if trainer is not None and member is not None:
            if data['is_active']:
                if TrainerMemberAssignment.objects.filter(
                    trainer=trainer, member=member, is_active=True
                ).exists():
                    return 'Active assignment already exists'
            elif TrainerMemberAssignment.objects.filter(
                trainer=trainer, member=member, is_active=False
            ).exists():
                return 'Assignment already exists'
        if data['is_active'] and member is not None:
            if TrainerMemberAssignment.objects.filter(member=member, is_active=True).exists():
                raise RowError(
                    'Member Email',
                    f'{data["member_email"]} already has an active trainer assignment.',
                )
        return None

    @classmethod
    def insert(cls, data, ctx):
        assignment = TrainerMemberAssignment.objects.create(
            trainer=ctx.require_user(data['trainer_email'], 'Trainer Email', role=User.Role.TRAINER),
            member=ctx.require_user(data['member_email'], 'Member Email', role=User.Role.MEMBER),
            end_date=data['end_date'],
            is_active=data['is_active'],
            notes=data['notes'],
        )
        if data['assigned_date']:
            # assigned_date is auto_now_add, so history is backfilled with a
            # targeted UPDATE that skips the field's "now" override.
            TrainerMemberAssignment.objects.filter(pk=assignment.pk).update(
                assigned_date=data['assigned_date']
            )
        return assignment


class ProgressSheet(Sheet):
    key = 'progress'
    name = 'Progress'
    aliases=('Progress Entries', 'Body Metrics', 'Measurements')
    description = 'Body-metric snapshots per member per date (one row per date).'
    columns = (
        Column('member_email', 'Member Email', aliases=('Email', 'Member'), required=True),
        Column('date', 'Date', required=True),
        Column('weight_kg', 'Weight (kg)', aliases=('Weight',)),
        Column('height_cm', 'Height (cm)', aliases=('Height',)),
        Column('body_fat_percentage', 'Body Fat %', aliases=('Body Fat', 'Body Fat Percentage')),
        Column('muscle_mass_kg', 'Muscle Mass (kg)', aliases=('Muscle Mass',)),
        Column('chest_cm', 'Chest (cm)', aliases=('Chest',)),
        Column('waist_cm', 'Waist (cm)', aliases=('Waist',)),
        Column('hips_cm', 'Hips (cm)', aliases=('Hips',)),
        Column('bicep_cm', 'Bicep (cm)', aliases=('Bicep',)),
        Column('thigh_cm', 'Thigh (cm)', aliases=('Thigh',)),
        Column('notes', 'Notes'),
    )
    parsers = {
        'date': p_date(),
        'weight_kg': p_decimal(),
        'height_cm': p_decimal(),
        'body_fat_percentage': p_decimal(minimum=0, maximum=100),
        'muscle_mass_kg': p_decimal(),
        'chest_cm': p_decimal(),
        'waist_cm': p_decimal(),
        'hips_cm': p_decimal(),
        'bicep_cm': p_decimal(),
        'thigh_cm': p_decimal(),
    }
    example = {
        'member_email': 'anita.sharma@example.com',
        'date': '2026-01-15',
        'weight_kg': '58.5',
        'height_cm': '165',
        'body_fat_percentage': '26.4',
        'muscle_mass_kg': '38.2',
        'chest_cm': '88',
        'waist_cm': '72',
        'hips_cm': '96',
        'bicep_cm': '28',
        'thigh_cm': '54',
        'notes': 'First check-in',
    }

    @classmethod
    def identity(cls, data):
        return (data['member_email'], data['date'])

    @classmethod
    def clean(cls, row_number, raw, ctx):
        data = super().clean(row_number, raw, ctx)
        ctx.resolve_user(data['member_email'], 'Member Email', role=User.Role.MEMBER)
        return data

    @classmethod
    def existing(cls, data, ctx):
        user = ctx.users.get(data['member_email'])
        if user is None:
            return None  # brand-new member, no history possible yet
        if ProgressEntry.objects.filter(member=user, date=data['date']).exists():
            return 'Progress entry already exists for this date'
        return None

    @classmethod
    def insert(cls, data, ctx):
        return ProgressEntry.objects.create(
            member=ctx.require_user(data['member_email'], 'Member Email', role=User.Role.MEMBER),
            date=data['date'],
            weight_kg=data['weight_kg'],
            height_cm=data['height_cm'],
            body_fat_percentage=data['body_fat_percentage'],
            muscle_mass_kg=data['muscle_mass_kg'],
            chest_cm=data['chest_cm'],
            waist_cm=data['waist_cm'],
            hips_cm=data['hips_cm'],
            bicep_cm=data['bicep_cm'],
            thigh_cm=data['thigh_cm'],
            recorded_by=ctx.actor,
            notes=data['notes'],
        )


# Import order — every sheet only references sheets listed before it.
SHEETS = (
    MembershipPlansSheet,
    MembersSheet,
    StaffSheet,
    TrainersSheet,
    OffersSheet,
    PromoCodesSheet,
    MembershipsSheet,
    PaymentsSheet,
    AttendanceSheet,
    EquipmentSheet,
    LockersSheet,
    LockerAssignmentsSheet,
    TrainerAssignmentsSheet,
    ProgressSheet,
)
