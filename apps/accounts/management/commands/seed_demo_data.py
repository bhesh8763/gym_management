"""
Management command: seed_demo_data

Builds a realistic, idempotent demo dataset for local development:
one gym + branch, an OWNER admin, 3 membership plans, 2 trainers,
2 receptionists, 25 members covering every membership status, trainer
assignments, payments (paid + pending), lockers, equipment, 30 days of
attendance with mixed sources, offers/promo codes, a QR token for every
member, weekly body-metric progress history, a small exercise library,
personal records, workout templates with assignments, and diet plans
with meals, meal logs, and checklists.

Safety rules:
  * Refuses to run when DEBUG is False.
  * Never deletes, overwrites, or resets anything: every object is looked
    up with get_or_create() / filter().first(); existing rows are counted
    as "already present" and left untouched.

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --password 'MySecret123!'
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.attendance.models import Attendance, QRAttendanceToken
from apps.diet.models import DietPlan, Meal, MealChecklist, MealLog
from apps.equipment.models import Equipment, MaintenanceRecord
from apps.gyms.models import Branch, BranchMembership, Gym, GymMembership
from apps.gyms.services import mark_gym_onboarded, provision_owner_gym
from apps.lockers.models import Locker, LockerAssignment
from apps.members.models import MemberProfile
from apps.memberships.models import (
    Membership,
    MembershipPlan,
    Offer,
    PromoCode,
    PromoCodeUsage,
)
from apps.payments.models import Payment
from apps.progress.models import PersonalRecord, ProgressEntry
from apps.staff.models import StaffProfile
from apps.trainers.models import TrainerMemberAssignment, TrainerProfile
from apps.workouts.models import (
    Exercise,
    WorkoutAssignment,
    WorkoutDay,
    WorkoutDayExercise,
    WorkoutTemplate,
)


def _round2(value):
    """Quantize a float/Decimal to 2 places for the DecimalField columns."""
    return Decimal(str(round(float(value), 2)))


class Command(BaseCommand):
    help = (
        'Seed idempotent demo data (gym, staff, 25 members, plans, payments, '
        'attendance, lockers, equipment, offers, QR tokens, progress history, '
        'exercises, PRs, workout templates/assignments, diet plans/logs). '
        'DEBUG only; never deletes or modifies existing rows.'
    )

    GYM_NAME = 'FitCore Gym'
    DEMO_DOMAIN = 'demo.fitcore.local'
    OWNER_EMAIL = 'admin@gmail.com'

    # (first, last, gender, category) — 25 members covering every status.
    MEMBERS = [
        # active + yearly plan (6)
        ('Aayush', 'Shrestha', 'M', 'active_yearly'),
        ('Priya', 'Gurung', 'F', 'active_yearly'),
        ('Bikash', 'Tamang', 'M', 'active_yearly'),
        ('Anjali', 'Rai', 'F', 'active_yearly'),
        ('Sujan', 'Maharjan', 'M', 'active_yearly'),
        ('Nisha', 'Thapa', 'F', 'active_yearly'),
        # active + monthly plan (7)
        ('Ramesh', 'Poudel', 'M', 'active_monthly'),
        ('Sabina', 'Limbu', 'F', 'active_monthly'),
        ('Deepak', 'KC', 'M', 'active_monthly'),
        ('Raksha', 'Lama', 'F', 'active_monthly'),
        ('Prakash', 'Adhikari', 'M', 'active_monthly'),
        ('Sunita', 'Magar', 'F', 'active_monthly'),
        ('Aakash', 'Basnet', 'M', 'active_monthly'),
        # no plan membership at all (5)
        ('Tanvi', 'Chaudhary', 'F', 'no_plan'),
        ('Nirajan', 'Silpakar', 'M', 'no_plan'),
        ('Riya', 'Panta', 'F', 'no_plan'),
        ('Sagar', 'Dangi', 'M', 'no_plan'),
        ('Kriti', 'Bajracharya', 'F', 'no_plan'),
        # frozen plan membership (3)
        ('Kamal', 'Bahadur', 'M', 'frozen'),
        ('Shreya', 'Koirala', 'F', 'frozen'),
        ('Manish', 'Ghale', 'M', 'frozen'),
        # pending payment (2)
        ('Anmol', 'Rana', 'M', 'pending'),
        ('Pooja', 'Adhikari', 'F', 'pending'),
        # expired (2)
        ('Rohit', 'Verma', 'M', 'expired'),
        ('Sushmita', 'Bista', 'F', 'expired'),
    ]

    PLANS = [
        {
            'key': 'monthly', 'name': 'Monthly', 'cycle': 'MONTHLY',
            'days': 30, 'price': '1500.00',
            'features': ['Gym floor access', 'Locker room access',
                         '1 body composition scan'],
        },
        {
            'key': 'quarterly', 'name': 'Quarterly', 'cycle': 'QUARTERLY',
            'days': 90, 'price': '4000.00',
            'features': ['Gym floor access', 'Locker room access',
                         '2 group classes per week'],
        },
        {
            'key': 'yearly', 'name': 'Yearly', 'cycle': 'ANNUAL',
            'days': 365, 'price': '15000.00',
            'features': ['Gym floor access', 'All group classes',
                         'Monthly personal training session', '4 guest passes'],
        },
    ]

    TRAINERS = [
        ('Anil', 'Rai', ['Strength Training', 'Bodybuilding'],
         [{'name': 'ACE CPT', 'issued': '2022-06'}], 7, '45000.00',
         'Strength and conditioning coach with 7 years of experience.'),
        ('Pema', 'Sherma', ['Yoga', 'Mobility'],
         [{'name': 'RYT-200', 'issued': '2021-09'}], 4, '40000.00',
         'Yoga and mobility specialist focused on injury prevention.'),
    ]

    RECEPTIONISTS = [
        ('Gita', 'Basnet', '25000.00'),
        ('Raj', 'Mishra', '25000.00'),
    ]

    EQUIPMENT = [
        ('Treadmill', 'Cardio', 'HealthStream', 'HS-T900', 'CARDIO-001', 2,
         'GOOD', 'Cardio Zone', '150000.00'),
        ('Elliptical Cross Trainer', 'Cardio', 'HealthStream', 'HS-E200',
         'CARDIO-002', 2, 'GOOD', 'Cardio Zone', '95000.00'),
        ('Stationary Bike', 'Cardio', 'ProForm', 'PF-B50', 'CARDIO-003', 3,
         'EXCELLENT', 'Cardio Zone', '45000.00'),
        ('Squat Rack', 'Free Weights', 'Rogue', 'RR-390', 'FREE-001', 2,
         'EXCELLENT', 'Free Weights Area', '120000.00'),
        ('Dumbbell Set 2.5-40kg', 'Free Weights', 'York', 'DB-SET-40',
         'FREE-002', 1, 'GOOD', 'Free Weights Area', '85000.00'),
        ('Adjustable Bench', 'Free Weights', 'Rogue', 'AB-310', 'FREE-003', 3,
         'GOOD', 'Free Weights Area', '40000.00'),
        ('Cable Crossover Machine', 'Machines', 'Life Fitness', 'LF-CC1',
         'MACH-001', 1, 'FAIR', 'Machine Floor', '220000.00'),
        ('Leg Press Machine', 'Machines', 'Life Fitness', 'LP-250',
         'MACH-002', 1, 'GOOD', 'Machine Floor', '130000.00'),
    ]

    # Global exercise library (name unique, no gym FK). A fresh local DB has
    # zero rows, and PersonalRecord rows cannot exist without these.
    EXERCISES = [
        ('Bench Press', 'CHEST', 'STRENGTH', 'Barbell'),
        ('Back Squat', 'LEGS', 'STRENGTH', 'Barbell'),
        ('Deadlift', 'BACK', 'STRENGTH', 'Barbell'),
        ('Overhead Press', 'SHOULDERS', 'STRENGTH', 'Barbell'),
        ('Pull-Up', 'BACK', 'STRENGTH', 'Bodyweight'),
        ('Plank', 'CORE', 'STRENGTH', 'Bodyweight'),
        ('5 KM Run', 'CARDIO', 'CARDIO', ''),
        ('Burpee', 'FULL_BODY', 'PLYO', 'Bodyweight'),
    ]

    # (exercise, unit, base value, value span) — PRs rotate through this
    # list deterministically per member: value = base + (i*7 + k*13) % span.
    PR_SPECS = [
        ('Bench Press', 'kg', 50, 40),
        ('Back Squat', 'kg', 70, 50),
        ('Deadlift', 'kg', 90, 60),
        ('Overhead Press', 'kg', 35, 30),
        ('Pull-Up', 'reps', 6, 10),
        ('Plank', 'seconds', 45, 60),
    ]

    # (name, goal, difficulty, duration_weeks, status, trainer_index,
    #  description, [(day_name, [(exercise, sets, reps, duration_s), ...]), ...])
    WORKOUT_TEMPLATES = [
        ('Strength Foundations', 'Strength', 'INTERMEDIATE', 4, 'APPROVED', 0,
         'Progressive barbell strength block for intermediate lifters.',
         [
             ('Push Day', [('Bench Press', 4, '6-8', None),
                           ('Overhead Press', 3, '8-10', None),
                           ('Plank', 3, None, 45)]),
             ('Pull Day', [('Deadlift', 4, '5', None),
                           ('Pull-Up', 4, 'AMRAP', None),
                           ('Plank', 3, None, 45)]),
             ('Leg Day', [('Back Squat', 4, '6-8', None),
                          ('Burpee', 3, None, 60)]),
         ]),
        ('Fat Loss Blast', 'Fat Loss', 'INTERMEDIATE', 6, 'APPROVED', 1,
         'High-intensity circuits pairing strength with conditioning.',
         [
             ('Full Body A', [('Back Squat', 3, '12-15', None),
                              ('Burpee', 4, None, 45),
                              ('Plank', 3, None, 60)]),
             ('Cardio Core', [('5 KM Run', 1, None, 1500),
                              ('Plank', 3, None, 60),
                              ('Pull-Up', 3, '8-12', None)]),
             ('Full Body B', [('Bench Press', 3, '10-12', None),
                              ('Burpee', 4, None, 45)]),
         ]),
        ('Hypertrophy Split', 'Hypertrophy', 'ADVANCED', 8, 'APPROVED', 0,
         'Volume-focused push/pull/legs split for muscle gain.',
         [
             ('Chest & Shoulders', [('Bench Press', 4, '8-12', None),
                                    ('Overhead Press', 3, '10-12', None)]),
             ('Back & Arms', [('Deadlift', 3, '8', None),
                              ('Pull-Up', 4, 'AMRAP', None)]),
             ('Legs', [('Back Squat', 4, '8-12', None),
                       ('Plank', 3, None, 60)]),
         ]),
        ('Mobility & Recovery', 'Mobility', 'BEGINNER', 4, 'APPROVED', 1,
         'Low-intensity mobility work for rest days and recovery.',
         [
             ('Flow A', [('Plank', 3, None, 45), ('Burpee', 2, None, 30)]),
             ('Flow B', [('5 KM Run', 1, None, 1200), ('Plank', 3, None, 45)]),
         ]),
        ('Tournament Prep Block', 'Performance', 'ADVANCED', 6, 'IN_REVIEW', 0,
         'Sport-specific power block awaiting owner approval.',
         [
             ('Power Day', [('Deadlift', 5, '3', None),
                            ('Overhead Press', 4, '5', None)]),
         ]),
        ('Beginner Starter Routine', 'General Fitness', 'BEGINNER', 2, 'DRAFT', 1,
         'Draft starter routine for new joiners.',
         [
             ('Easy Day', [('Plank', 2, None, 30), ('5 KM Run', 1, None, 900)]),
         ]),
    ]

    # Diet plan goal → (plan goal, kcal, protein, carbs, fats). Member
    # fitness goals that have no diet equivalent map to MAINTENANCE.
    DIET_GOALS = {
        'WEIGHT_LOSS': ('WEIGHT_LOSS', 1800, 150, 180, 60),
        'MUSCLE_GAIN': ('MUSCLE_GAIN', 2600, 180, 300, 80),
        'ENDURANCE': ('ENDURANCE', 2400, 140, 320, 70),
        'FLEXIBILITY': ('MAINTENANCE', 2200, 160, 250, 70),
        'GENERAL': ('MAINTENANCE', 2200, 160, 250, 70),
    }

    # (meal_type, food, portion, calories, time) — appended to every plan.
    DIET_MEALS = [
        ('BREAKFAST', 'Oatmeal with banana & peanuts', '1 bowl', 420, time(7, 30)),
        ('LUNCH', 'Grilled chicken breast with brown rice', '1 plate', 620, time(12, 30)),
        ('EVENING_SNACK', 'Greek yogurt with almonds', '200 g', 250, time(16, 30)),
        ('DINNER', 'Salmon, quinoa & mixed salad', '1 plate', 550, time(19, 0)),
    ]

    # Rotating daily intake for MealLog rows ({"name","amount","calories"}).
    FOOD_ROTATION = [
        [{'name': 'Oatmeal', 'amount': '1 bowl', 'calories': 420},
         {'name': 'Chicken & rice', 'amount': '1 plate', 'calories': 620},
         {'name': 'Salmon salad', 'amount': '1 plate', 'calories': 550}],
        [{'name': 'Eggs & toast', 'amount': '3 eggs', 'calories': 330},
         {'name': 'Lentil curry & rice', 'amount': '1 plate', 'calories': 580}],
        [{'name': 'Protein shake', 'amount': '1 scoop', 'calories': 180},
         {'name': 'Turkey wrap', 'amount': '1 wrap', 'calories': 460},
         {'name': 'Fruit bowl', 'amount': '1 bowl', 'calories': 210}],
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            '--password', default='Admin@12345',
            help='Password for the OWNER admin account (default: Admin@12345).',
        )
        parser.add_argument(
            '--demo-password', default='Demo@12345',
            help='Password shared by every other demo account (default: Demo@12345).',
        )

    # ─── helpers ──────────────────────────────────────────────────────────────

    def _tally(self, key, created):
        counts = self.stats.setdefault(key, [0, 0])
        counts[0 if created else 1] += 1

    def _make_user(self, email, password, *, role, first, last, phone='',
                    is_staff=False, is_superuser=False):
        user = User.objects.filter(email=email).first()
        if user is not None:
            self._tally('users', False)
            return user
        user = User.objects.create_user(
            email, password,
            first_name=first, last_name=last, phone=phone, role=role,
            is_staff=is_staff, is_superuser=is_superuser,
        )
        self._tally('users', True)
        return user

    def _link_to_gym(self, user, gym, branch, role, *, can_manage=False):
        gm, gm_created = GymMembership.objects.get_or_create(
            user=user, gym=gym,
            defaults={
                'role': role,
                'status': GymMembership.Status.ACTIVE,
                'is_default': True,
            },
        )
        self._tally('gym_memberships', gm_created)
        bm, bm_created = BranchMembership.objects.get_or_create(
            gym_membership=gm, branch=branch,
            defaults={'can_manage': can_manage},
        )
        self._tally('branch_memberships', bm_created)
        return gm

    def _membership_spec(self, category, seq, today):
        """Deterministic Membership field values for one member category."""
        if category == 'active_yearly':
            start = today - timedelta(days=45)
            return {
                'plan_key': 'yearly', 'status': Membership.Status.ACTIVE,
                'start': start, 'end': start + timedelta(days=365),
                'price_paid': Decimal('15000.00'),
            }
        if category == 'active_monthly':
            start = today - timedelta(days=12)
            return {
                'plan_key': 'monthly', 'status': Membership.Status.ACTIVE,
                'start': start, 'end': start + timedelta(days=30),
                'price_paid': Decimal('1500.00'),
            }
        if category == 'frozen':
            start = today - timedelta(days=60)
            return {
                'plan_key': 'yearly', 'status': Membership.Status.FROZEN,
                'start': start, 'end': start + timedelta(days=365),
                'price_paid': Decimal('15000.00'),
                'freeze_start': today - timedelta(days=5),
                'freeze_end': today + timedelta(days=25),
                'freeze_reason': 'Demo: member requested a travel freeze.',
            }
        if category == 'pending':
            return {
                'plan_key': 'monthly', 'status': Membership.Status.PENDING,
                'start': today, 'end': today + timedelta(days=30),
                'price_paid': Decimal('0'),
            }
        if category == 'expired':
            offset = (40, 100)[seq % 2]
            start = today - timedelta(days=offset)
            return {
                'plan_key': 'monthly', 'status': Membership.Status.EXPIRED,
                'start': start, 'end': start + timedelta(days=30),
                'price_paid': Decimal('1500.00'),
            }
        return None  # no_plan

    # ─── seed sections ────────────────────────────────────────────────────────

    def _seed_gym(self, owner):
        gym = Gym.objects.filter(name=self.GYM_NAME).first()
        owner_gm = None
        if gym is not None:
            if gym.owner_id not in (None, owner.id):
                raise CommandError(
                    f'Gym "{self.GYM_NAME}" already exists but belongs to another '
                    'owner; refusing to seed into it.'
                )
            self._tally('gyms', False)
            gym_created = False
        else:
            gym, owner_gm = provision_owner_gym(user=owner, name=self.GYM_NAME)
            gym.address = 'Durbarmarg, Kathmandu'
            gym.phone = '+977-1-4000000'
            gym.save(update_fields=['address', 'phone', 'updated_at'])
            mark_gym_onboarded(gym)  # ACTIVE + onboarding_complete
            self._tally('gyms', True)
            self._tally('gym_memberships', True)  # provision made the owner row
            gym_created = True

        branch = gym.branches.filter(code='MAIN').first()
        if branch is None:
            branch = Branch.objects.create(
                gym=gym, name='Main Branch', code='MAIN',
                is_primary=True, status=Branch.Status.ACTIVE,
                address='Durbarmarg, Kathmandu',
            )
            self._tally('branches', True)
        else:
            # On the fresh path provision_owner_gym just created it this run.
            self._tally('branches', gym_created)

        if owner_gm is None:
            owner_gm = self._link_to_gym(
                owner, gym, branch, GymMembership.Role.OWNER, can_manage=True,
            )
        else:
            bm, bm_created = BranchMembership.objects.get_or_create(
                gym_membership=owner_gm, branch=branch,
                defaults={'can_manage': True},
            )
            self._tally('branch_memberships', bm_created)
        return gym, branch, owner_gm

    def _seed_plans(self, gym, branch):
        plans = {}
        for spec in self.PLANS:
            plan, created = MembershipPlan.objects.get_or_create(
                gym=gym, name=spec['name'],
                defaults={
                    'branch': branch,
                    'description': f"{spec['name']} membership plan (demo).",
                    'billing_cycle': spec['cycle'],
                    'duration_days': spec['days'],
                    'price': Decimal(spec['price']),
                    'features': list(spec['features']),
                    'is_active': True,
                },
            )
            self._tally('membership_plans', created)
            plans[spec['key']] = plan
        return plans

    def _seed_offers(self, gym, owner, today):
        now = timezone.now()
        valid_from = now - timedelta(days=15)
        valid_until = now + timedelta(days=60)

        offer1, created = Offer.objects.get_or_create(
            gym=gym, name='New Year Blast',
            defaults={
                'description': '20% off every plan (demo offer).',
                'discount_type': Offer.DiscountType.PERCENTAGE,
                'discount_value': Decimal('20.00'),
                'applicability': Offer.Applicability.ALL_PLANS,
                'valid_from': valid_from, 'valid_until': valid_until,
                'is_active': True,
            },
        )
        self._tally('offers', created)

        offer2, created = Offer.objects.get_or_create(
            gym=gym, name='Flat 500 Off Quarterly',
            defaults={
                'description': 'NPR 500 off the quarterly plan (demo offer).',
                'discount_type': Offer.DiscountType.FIXED_AMOUNT,
                'discount_value': Decimal('500.00'),
                'applicability': Offer.Applicability.SPECIFIC_PLANS,
                'valid_from': valid_from, 'valid_until': valid_until,
                'is_active': True,
            },
        )
        self._tally('offers', created)
        if created:
            quarterly = MembershipPlan.objects.filter(
                gym=gym, name='Quarterly',
            ).first()
            if quarterly is not None:
                offer2.plans.set([quarterly])

        promos = {}
        for code, offer, max_uses in (
            ('WELCOME20', offer1, 50),
            ('NEWYEAR20', offer1, 25),
            ('FLAT500', offer2, 10),
        ):
            promo, created = PromoCode.objects.get_or_create(
                gym=gym, code=code,
                defaults={
                    'offer': offer,
                    'status': PromoCode.Status.ACTIVE,
                    'max_uses': max_uses,
                    'valid_from': valid_from, 'valid_until': valid_until,
                    'created_by': owner,
                },
            )
            self._tally('promo_codes', created)
            promos[code] = promo
        return promos

    def _seed_staff(self, gym, branch, demo_password, today):
        trainers = []
        for first, last, specs, certs, years, salary, bio in self.TRAINERS:
            email = f'{first}.{last}@{self.DEMO_DOMAIN}'.lower()
            user = self._make_user(
                email, demo_password, role=User.Role.TRAINER,
                first=first, last=last,
                phone=f'98{21000000 + len(trainers)}',
            )
            self._link_to_gym(user, gym, branch, GymMembership.Role.TRAINER)
            profile, created = TrainerProfile.objects.get_or_create(
                user=user, gym=gym,
                defaults={
                    'branch': branch, 'specializations': specs,
                    'certifications': certs, 'experience_years': years,
                    'bio': bio, 'joined_date': today - timedelta(days=200),
                    'salary': Decimal(salary), 'is_available': True,
                },
            )
            self._tally('trainer_profiles', created)
            # The staff directory reads StaffProfile rows — trainers need one
            # too, or they're invisible there (seed previously only gave
            # receptionists a StaffProfile). Idempotent: (user, gym) is unique,
            # so re-running the seed won't duplicate it.
            _, staff_created = StaffProfile.objects.get_or_create(
                user=user, gym=gym,
                defaults={
                    'branch': branch,
                    'role': StaffProfile.Role.TRAINER,
                    'joined_date': today - timedelta(days=200),
                    'salary': Decimal(salary),
                },
            )
            self._tally('staff_profiles', staff_created)
            trainers.append(user)

        receptionists = []
        for idx, (first, last, salary) in enumerate(self.RECEPTIONISTS):
            email = f'{first}.{last}@{self.DEMO_DOMAIN}'.lower()
            user = self._make_user(
                email, demo_password, role=User.Role.STAFF,
                first=first, last=last,
                phone=f'98{22000000 + idx}',
            )
            self._link_to_gym(
                user, gym, branch, GymMembership.Role.STAFF, can_manage=True,
            )
            profile, created = StaffProfile.objects.get_or_create(
                user=user, gym=gym,
                defaults={
                    'branch': branch,
                    'role': StaffProfile.Role.RECEPTIONIST,
                    'joined_date': today - timedelta(days=180),
                    'salary': Decimal(salary),
                },
            )
            self._tally('staff_profiles', created)
            receptionists.append(user)
        return trainers, receptionists

    def _seed_members(self, gym, branch, plans, promos, demo_password, today):
        goals = ['WEIGHT_LOSS', 'MUSCLE_GAIN', 'ENDURANCE', 'FLEXIBILITY', 'GENERAL']
        levels = ['BEGINNER', 'INTERMEDIATE', 'ADVANCED']
        seq_per_category = {}
        rows = []

        for i, (first, last, gender, category) in enumerate(self.MEMBERS):
            seq = seq_per_category.get(category, 0)
            seq_per_category[category] = seq + 1

            email = f'member{i + 1:02d}@{self.DEMO_DOMAIN}'
            user = self._make_user(
                email, demo_password, role=User.Role.MEMBER,
                first=first, last=last, phone=f'98{20000000 + i}',
            )
            self._link_to_gym(
                user, gym, branch, GymMembership.Role.MEMBER,
            )

            _, profile_created = MemberProfile.objects.get_or_create(
                user=user, gym=gym,
                defaults={
                    'branch': branch,
                    'date_of_birth': date(1990 + i % 15, i % 12 + 1, i % 27 + 1),
                    'gender': gender,
                    'address': f'Demo House {i + 1}, Kathmandu',
                    'emergency_contact_name': f'{last} Family',
                    'emergency_contact_phone': f'98{30000000 + i}',
                    'height_cm': Decimal(150 + i % 40),
                    'weight_kg': Decimal(52 + i % 35),
                    'fitness_goal': goals[i % len(goals)],
                    'fitness_level': levels[i % len(levels)],
                    'notes': 'Seeded demo member.',
                },
            )
            self._tally('member_profiles', profile_created)

            spec = self._membership_spec(category, seq, today)
            membership = None
            if spec is not None:
                promo = None
                price_paid = spec['price_paid']
                # First yearly member uses the WELCOME20 promo (20% off).
                if category == 'active_yearly' and seq == 0 and 'WELCOME20' in promos:
                    promo = promos['WELCOME20']
                    price_paid = Decimal('12000.00')

                membership = Membership.objects.filter(
                    gym=gym, member=user,
                ).order_by('-start_date').first()
                if membership is not None:
                    self._tally('memberships', False)
                else:
                    membership = Membership.objects.create(
                        gym=gym, branch=branch, member=user,
                        plan=plans[spec['plan_key']],
                        status=spec['status'],
                        start_date=spec['start'], end_date=spec['end'],
                        price_paid=price_paid, promo_code=promo,
                        freeze_start=spec.get('freeze_start'),
                        freeze_end=spec.get('freeze_end'),
                        freeze_reason=spec.get('freeze_reason', ''),
                        notes='Seeded demo membership.',
                    )
                    self._tally('memberships', True)
                    if promo is not None:
                        self._seed_promo_usage(
                            promo, user, membership,
                            gym, branch,
                            original=Decimal('15000.00'),
                            discount=Decimal('3000.00'),
                            final=Decimal('12000.00'),
                        )

            rows.append({
                'index': i, 'user': user, 'category': category,
                'gender': gender, 'membership': membership, 'spec': spec,
            })
        return rows

    def _seed_promo_usage(self, promo, member, membership, gym, branch,
                          *, original, discount, final):
        usage = PromoCodeUsage.objects.filter(
            promo_code=promo, member=member,
        ).first()
        if usage is not None:
            self._tally('promo_usages', False)
            return
        PromoCodeUsage.objects.create(
            gym=gym, branch=branch, promo_code=promo, member=member,
            membership=membership, original_price=original,
            discount_applied=discount, final_price=final,
        )
        self._tally('promo_usages', True)
        if promo.used_count < promo.max_uses:
            promo.redeem()

    def _seed_trainer_assignments(self, gym, branch, member_rows, trainers):
        active = [r for r in member_rows if r['category'].startswith('active_')]
        for idx, row in enumerate(active):
            trainer = trainers[idx % len(trainers)]
            exists = TrainerMemberAssignment.objects.filter(
                gym=gym, member=row['user'], is_active=True,
            ).exists()
            if exists:
                self._tally('trainer_assignments', False)
                continue
            TrainerMemberAssignment.objects.create(
                gym=gym, branch=branch, trainer=trainer,
                member=row['user'], is_active=True,
                notes='Seeded demo trainer assignment.',
            )
            self._tally('trainer_assignments', True)

    def _seed_lockers(self, gym, branch, owner, member_rows):
        fee = Decimal('500.00')
        lockers = {}
        for n in range(1, 13):
            number = f'L-{n:02d}'
            status = Locker.LockerStatus.AVAILABLE
            if n == 11:
                status = Locker.LockerStatus.MAINTENANCE
            elif n == 12:
                status = Locker.LockerStatus.RESERVED
            locker, created = Locker.objects.get_or_create(
                gym=gym, branch=branch, locker_number=number,
                defaults={
                    'location': "Men's Block A" if n <= 8 else "Women's Block B",
                    'status': status, 'monthly_fee': fee,
                    'notes': 'Seeded demo locker.',
                },
            )
            self._tally('lockers', created)
            lockers[number] = locker

        # 4 male active members in Men's Block A, 2 female in Women's Block B.
        male = [r for r in member_rows
                if r['category'].startswith('active_') and r['gender'] == 'M'][:4]
        female = [r for r in member_rows
                  if r['category'].startswith('active_') and r['gender'] == 'F'][:2]
        assignments = (
            [(male[0], 'L-01'), (male[1], 'L-02'), (male[2], 'L-03'),
             (male[3], 'L-04'), (female[0], 'L-09'), (female[1], 'L-10')]
            if len(male) >= 4 and len(female) >= 2 else []
        )

        for row, number in assignments:
            locker = lockers[number]
            assignment = LockerAssignment.objects.filter(
                locker=locker, member=row['user'],
            ).first()
            if assignment is None:
                LockerAssignment.objects.create(
                    gym=gym, branch=branch, locker=locker,
                    member=row['user'],
                    start_date=timezone.localdate() - timedelta(days=30),
                    is_active=True, assigned_by=owner,
                )
                self._tally('locker_assignments', True)
            else:
                self._tally('locker_assignments', False)
            if locker.status != Locker.LockerStatus.OCCUPIED:
                locker.status = Locker.LockerStatus.OCCUPIED
                locker.save(update_fields=['status', 'updated_at'])

    def _seed_equipment(self, gym, branch, owner, today):
        for idx, (name, category, brand, model, code, qty, condition,
                  location, price) in enumerate(self.EQUIPMENT):
            item, created = Equipment.objects.get_or_create(
                gym=gym, serial_number=f'SEED-{code}',
                defaults={
                    'branch': branch, 'name': name, 'category': category,
                    'brand': brand, 'model_number': model, 'quantity': qty,
                    'purchase_date': date(2023, idx % 12 + 1, 5 + idx % 20),
                    'purchase_price': Decimal(price),
                    'condition': condition, 'location': location,
                    'notes': 'Seeded demo equipment.',
                },
            )
            self._tally('equipment', created)

        treadmill = Equipment.objects.filter(
            gym=gym, serial_number='SEED-CARDIO-001',
        ).first()
        if treadmill is not None:
            record, created = MaintenanceRecord.objects.get_or_create(
                equipment=treadmill,
                maintenance_type=MaintenanceRecord.MaintenanceType.ROUTINE,
                scheduled_date=today - timedelta(days=40),
                defaults={
                    'gym': gym, 'branch': branch,
                    'status': MaintenanceRecord.MaintenanceStatus.COMPLETED,
                    'completed_date': today - timedelta(days=40),
                    'performed_by': 'Kumar Service Center',
                    'cost': Decimal('2500.00'),
                    'description': 'Routine belt lubrication and calibration.',
                    'recorded_by': owner,
                },
            )
            self._tally('maintenance_records', created)

        leg_press = Equipment.objects.filter(
            gym=gym, serial_number='SEED-MACH-002',
        ).first()
        if leg_press is not None:
            record, created = MaintenanceRecord.objects.get_or_create(
                equipment=leg_press,
                maintenance_type=MaintenanceRecord.MaintenanceType.REPAIR,
                scheduled_date=today + timedelta(days=10),
                defaults={
                    'gym': gym, 'branch': branch,
                    'status': MaintenanceRecord.MaintenanceStatus.SCHEDULED,
                    'description': 'Replace worn seat upholstery.',
                    'recorded_by': owner,
                },
            )
            self._tally('maintenance_records', created)

    def _seed_payments(self, gym, branch, owner, receptionists, member_rows):
        methods = [Payment.PaymentMethod.CASH, Payment.PaymentMethod.ESEWA,
                   Payment.PaymentMethod.KHALTI, Payment.PaymentMethod.BANK_TRANSFER]
        digital = {Payment.PaymentMethod.ESEWA, Payment.PaymentMethod.KHALTI,
                   Payment.PaymentMethod.BANK_TRANSFER}

        n = 0
        for row in member_rows:
            membership = row['membership']
            if membership is None:
                continue
            n += 1
            pending = membership.status == Membership.Status.PENDING
            method = methods[(n - 1) % len(methods)]
            status = (Payment.PaymentStatus.PENDING if pending
                      else Payment.PaymentStatus.PAID)
            discount = Decimal('3000.00') if membership.promo_code_id else Decimal('0')
            receipt = f'SEED-MEM-{n:03d}'

            payment, created = Payment.objects.get_or_create(
                receipt_number=receipt,
                defaults={
                    'gym': gym, 'branch': branch, 'member': row['user'],
                    'membership': membership,
                    'payment_for': Payment.PaymentFor.MEMBERSHIP,
                    'amount': membership.plan.price, 'discount': discount,
                    'payment_method': method, 'status': status,
                    'transaction_id': (
                        f'TXN-SEED-{n:04d}' if method in digital else ''
                    ),
                    'paid_at': (timezone.now() - timedelta(days=(n * 3) % 45)
                                if status == Payment.PaymentStatus.PAID else None),
                    'collected_by': (
                        owner if n % 2 else receptionists[0]
                    ),
                    'notes': 'Seeded demo payment.',
                },
            )
            self._tally('payments', created)

        # Locker rental payments for the six assigned lockers.
        locker_holders = [
            r for r in member_rows
            if LockerAssignment.objects.filter(
                member=r['user'], is_active=True,
            ).exists()
        ]
        for i, row in enumerate(locker_holders, start=1):
            receipt = f'SEED-LKR-{i:02d}'
            payment, created = Payment.objects.get_or_create(
                receipt_number=receipt,
                defaults={
                    'gym': gym, 'branch': branch, 'member': row['user'],
                    'membership': None,
                    'payment_for': Payment.PaymentFor.LOCKER,
                    'amount': Decimal('1500.00'), 'discount': Decimal('0'),
                    'payment_method': Payment.PaymentMethod.CASH,
                    'status': Payment.PaymentStatus.PAID,
                    'paid_at': timezone.now() - timedelta(days=10),
                    'collected_by': receptionists[1],
                    'notes': 'Seeded demo locker rental (3 months).',
                },
            )
            self._tally('payments', created)

    def _seed_qr_tokens(self, gym, branch, member_rows):
        for row in member_rows:
            exists = QRAttendanceToken.objects.filter(
                member=row['user'], gym=gym,
            ).exists()
            if exists:
                self._tally('qr_tokens', False)
                continue
            QRAttendanceToken.get_or_create_for_member(
                row['user'], gym=gym, branch=branch,
            )
            self._tally('qr_tokens', True)

    def _seed_attendance(self, gym, branch, owner, member_rows,
                         trainers, receptionists, today):
        window = [today - timedelta(days=d) for d in range(29, -1, -1)]
        sources = [Attendance.Source.QR, Attendance.Source.QR,
                   Attendance.Source.QR, Attendance.Source.BIOMETRIC,
                   Attendance.Source.MANUAL]

        # Members
        for m_idx, row in enumerate(member_rows):
            membership, spec = row['membership'], row['spec']
            if membership is None or spec is None or row['category'] == 'pending':
                continue  # no_plan / pending members do not attend
            category = row['category']
            lo = membership.start_date
            if category == 'frozen':
                hi = spec['freeze_start'] - timedelta(days=1)
            elif category == 'expired':
                hi = membership.end_date
            else:
                hi = today
            if hi < lo:
                continue

            for d_idx, day in enumerate(window):
                if day < lo or day > hi:
                    continue
                slot = m_idx * 37 + d_idx * 13
                absent = (m_idx + d_idx) % 7 == 3 or slot % 23 == 0
                defaults = {
                    'branch': branch,
                    'attendance_type': Attendance.AttendanceType.MEMBER,
                }
                if absent:
                    defaults.update({
                        'status': Attendance.Status.ABSENT,
                        'source': Attendance.Source.MANUAL,
                        'marked_by': owner,
                        'notes': 'Marked absent (demo).',
                    })
                else:
                    morning = m_idx % 2 == 0
                    hour = (6 if morning else 17) + slot % 3
                    minute = (slot * 7) % 60
                    check_in = time(hour, minute)
                    duration = 45 + (slot % 5) * 15
                    check_out = (
                        datetime.combine(day, check_in) + timedelta(minutes=duration)
                    ).time()
                    source = sources[slot % len(sources)]
                    defaults.update({
                        'status': Attendance.Status.PRESENT,
                        'check_in': check_in, 'check_out': check_out,
                        'source': source,
                        'marked_by': owner if source == Attendance.Source.MANUAL else None,
                    })
                _, created = Attendance.objects.get_or_create(
                    gym=gym, user=row['user'], date=day, defaults=defaults,
                )
                self._tally('attendance', created)

        # Staff / trainers: Monday-Saturday day shift.
        day_rows = (
            [(u, Attendance.AttendanceType.STAFF) for u in receptionists]
            + [(u, Attendance.AttendanceType.TRAINER) for u in trainers]
        )
        for s_idx, (user, atype) in enumerate(day_rows):
            for d_idx, day in enumerate(window):
                if day.weekday() == 6:  # Sunday off
                    continue
                if (s_idx + d_idx) % 11 == 5:  # occasional day off
                    continue
                slot = s_idx * 31 + d_idx * 7
                if atype == Attendance.AttendanceType.STAFF:
                    check_in = time(9, (slot * 3) % 45)
                    check_out = time(17, (slot * 5) % 45)
                else:
                    check_in = time(6, (slot * 3) % 30)
                    check_out = time(14, (slot * 5) % 45)
                source = [Attendance.Source.QR, Attendance.Source.BIOMETRIC,
                          Attendance.Source.MANUAL][slot % 3]
                _, created = Attendance.objects.get_or_create(
                    gym=gym, user=user, date=day,
                    defaults={
                        'branch': branch, 'attendance_type': atype,
                        'status': Attendance.Status.PRESENT,
                        'check_in': check_in, 'check_out': check_out,
                        'source': source,
                        'marked_by': owner if source == Attendance.Source.MANUAL else None,
                    },
                )
                self._tally('attendance', created)

    # ─── progress history ────────────────────────────────────────────────────

    def _seed_exercises(self, owner):
        """Global exercise library — PersonalRecords cannot exist without it."""
        library = {}
        for name, group, etype, equipment in self.EXERCISES:
            exercise, created = Exercise.objects.get_or_create(
                name=name,
                defaults={
                    'muscle_group': group,
                    'exercise_type': etype,
                    'equipment': equipment,
                    'created_by': owner,
                },
            )
            self._tally('exercises', created)
            library[name] = exercise
        return library

    def _seed_progress(self, gym, branch, owner, member_rows, today):
        """Weekly body-metric snapshots so history tables and charts have data.

        Windows are category-appropriate: active members get 12 weeks up to
        today, frozen/expired members stop where their membership stopped,
        pending/no-plan members get a recent trial window. Metrics drift in
        the member's seeded fitness-goal direction (weight down for
        WEIGHT_LOSS, up for MUSCLE_GAIN, wobbling otherwise) so the Weight
        Trend chart shows a real curve. Unique on (gym, member, date).
        """
        for row in member_rows:
            user, category = row['user'], row['category']
            membership, spec = row['membership'], row['spec']
            profile = MemberProfile.objects.filter(user=user, gym=gym).first()
            height = (
                _round2(profile.height_cm)
                if profile and profile.height_cm else Decimal('170.00')
            )
            weight = (
                _round2(profile.weight_kg)
                if profile and profile.weight_kg else Decimal('70.00')
            )
            goal = (getattr(profile, 'fitness_goal', '') or 'GENERAL')

            # Category windows — never seed outside the member's real span.
            if category in ('pending', 'no_plan'):
                hi, lo = today - timedelta(days=1), today - timedelta(days=43)
            elif category == 'frozen':
                hi = spec['freeze_start'] - timedelta(days=1)
                lo = max(membership.start_date, hi - timedelta(days=84))
            elif category == 'expired':
                hi = membership.end_date
                lo = max(membership.start_date, hi - timedelta(days=84))
            else:  # active_yearly / active_monthly
                hi, lo = today, today - timedelta(days=84)
            hi = min(hi, today)
            if hi < lo:
                continue

            i = row['index']
            gender = row['gender']
            # Per-week change; today's value sits at `hi`, older weeks drift
            # backwards along the trend.
            weight_delta = {
                'WEIGHT_LOSS': Decimal('-0.40'),
                'MUSCLE_GAIN': Decimal('0.25'),
                'ENDURANCE': Decimal('-0.20'),
            }.get(goal, Decimal('0.10') * (1 if i % 2 else -1))
            bf_now = _round2(18.5 + i % 4 if gender == 'M' else 23.5 + i % 5)
            mm_now = _round2(31 + i % 6 if gender == 'M' else 24 + i % 5)
            waist_now = _round2(84 + i % 10 if gender == 'M' else 76 + i % 10)
            hips_now = _round2(94 + i % 6 if gender == 'M' else 98 + i % 8)
            chest_now = _round2(98 + i % 8 if gender == 'M' else 92 + i % 8)
            bicep_now = _round2(33 + i % 6 if gender == 'M' else 27 + i % 5)
            thigh_now = _round2(55 + i % 8 if gender == 'M' else 53 + i % 8)

            day, week = hi, 0
            while day >= lo:
                _, created = ProgressEntry.objects.get_or_create(
                    gym=gym, member=user, date=day,
                    defaults={
                        'branch': branch,
                        'weight_kg': _round2(max(
                            Decimal('35.00'), weight - weight_delta * week,
                        )),
                        'height_cm': height,
                        'body_fat_percentage': _round2(max(
                            Decimal('6.00'), bf_now + Decimal('0.25') * week,
                        )),
                        'muscle_mass_kg': _round2(max(
                            Decimal('15.00'), mm_now - Decimal('0.20') * week,
                        )),
                        'chest_cm': _round2(chest_now - Decimal('0.10') * week),
                        'waist_cm': _round2(waist_now + Decimal('0.30') * week),
                        'hips_cm': _round2(hips_now + Decimal('0.15') * week),
                        'bicep_cm': _round2(bicep_now - Decimal('0.10') * week),
                        'thigh_cm': _round2(thigh_now - Decimal('0.10') * week),
                        'recorded_by': owner,
                        'notes': 'Seeded demo progress entry.',
                    },
                )
                self._tally('progress_entries', created)
                week += 1
                day -= timedelta(days=7)

    def _seed_personal_records(self, gym, member_rows, exercises, today):
        """Three PRs per member so the Personal Records table is never empty."""
        for row in member_rows:
            category = row['category']
            membership = row['membership']
            if category in ('pending', 'no_plan'):
                hi = today - timedelta(days=1)
            elif category == 'frozen':
                hi = row['spec']['freeze_start'] - timedelta(days=1)
            elif category == 'expired':
                hi = membership.end_date
            else:
                hi = today
            i = row['index']
            for k in range(3):
                name, unit, base, span = self.PR_SPECS[
                    (i + k) % len(self.PR_SPECS)
                ]
                exercise = exercises.get(name)
                if exercise is None:
                    continue
                value = _round2(base + (i * 7 + k * 13) % span)
                pr_date = hi - timedelta(days=7 * (k + 1))
                _, created = PersonalRecord.objects.get_or_create(
                    gym=gym, member=row['user'], exercise=exercise,
                    date=pr_date,
                    defaults={
                        'value': value,
                        'unit': unit,
                        'best_weight_kg': value if unit == 'kg' else None,
                        'best_reps': int(value) if unit == 'reps' else None,
                        'best_duration_seconds': (
                            int(value) if unit == 'seconds' else None
                        ),
                        'notes': 'Seeded demo PR.',
                    },
                )
                self._tally('personal_records', created)

    def _seed_workouts(self, gym, branch, owner, trainers, member_rows,
                       exercises, today):
        """Workout templates (with days/exercises) plus member assignments.

        Six templates across the full workflow — four APPROVED (assignable),
        one IN_REVIEW and one DRAFT — so the status filter and review flow
        have something to show. Active members are rotated onto the approved
        templates with a mix of ACTIVE / PAUSED / COMPLETED statuses so the
        TEMPLATES, APPROVED and ACTIVE ASSIGNMENTS cards all populate.
        """
        templates = []
        for spec in self.WORKOUT_TEMPLATES:
            (name, goal, difficulty, weeks, status,
             trainer_idx, description, days) = spec
            template, created = WorkoutTemplate.objects.get_or_create(
                gym=gym, name=name,
                defaults={
                    'branch': branch,
                    'trainer': trainers[trainer_idx % len(trainers)],
                    'goal': goal,
                    'description': description,
                    'difficulty': difficulty,
                    'status': status,
                    'duration_weeks': weeks,
                    'reviewed_by': owner if status == 'APPROVED' else None,
                },
            )
            self._tally('workout_templates', created)
            templates.append(template)

            for day_number, (day_name, day_exercises) in enumerate(days, start=1):
                day, day_created = WorkoutDay.objects.get_or_create(
                    template=template, week_number=1, day_number=day_number,
                    defaults={'day_name': day_name},
                )
                self._tally('workout_days', day_created)
                for order, (ex_name, sets, reps, duration) in enumerate(
                    day_exercises, start=1,
                ):
                    exercise = exercises.get(ex_name)
                    if exercise is None:
                        continue
                    _, placed = WorkoutDayExercise.objects.get_or_create(
                        workout_day=day, exercise=exercise, order=order,
                        defaults={
                            'sets': sets,
                            'reps': reps or '',
                            'duration_seconds': duration,
                        },
                    )
                    self._tally('workout_day_exercises', placed)

        # Assignments: only APPROVED templates are assignable; rotate a few
        # into PAUSED/COMPLETED so the status column isn't uniformly green.
        approved = [t for t in templates if t.status == WorkoutTemplate.Status.APPROVED]
        assigned_members = [
            r for r in member_rows if r['category'].startswith('active_')
        ]
        goal_notes = [
            'Seeded demo assignment.',
            'Fat loss focus for the season.',
            'Post-injury comeback plan.',
            'Strength before competition.',
        ]
        for idx, row in enumerate(assigned_members):
            template = approved[idx % len(approved)]
            if idx % 6 == 5:
                status = WorkoutAssignment.Status.COMPLETED
            elif idx % 4 == 3:
                status = WorkoutAssignment.Status.PAUSED
            else:
                status = WorkoutAssignment.Status.ACTIVE
            _, created = WorkoutAssignment.objects.get_or_create(
                gym=gym, template=template, member=row['user'],
                defaults={
                    'branch': branch,
                    'assigned_by': (
                        owner if idx % 2 == 0
                        else trainers[idx % len(trainers)]
                    ),
                    'status': status,
                    'start_date': today - timedelta(days=7 + idx * 5),
                    'goal_note': goal_notes[idx % len(goal_notes)],
                },
            )
            self._tally('workout_assignments', created)

    def _seed_diet(self, gym, branch, owner, trainers, member_rows, today):
        """Diet plans (with meals), week-long meal logs, and checklists.

        Active members get a goal-matched plan with a four-meal day plan;
        every fourth one also gets an INACTIVE legacy plan so the stats
        distinguish total vs active. The last 7 days get MealLog rows
        (rotating food lists, skipped days for realism) and MealChecklist
        rows with partial-to-full completion, feeding the daily/weekly
        summaries and adherence monitor.
        """
        default_goal = ('MAINTENANCE', 2200, 160, 250, 70)
        # Every member gets a plan so any selection in member pickers (and
        # member-detail adherence) has data — pending/no-plan included.
        assignable = list(member_rows)

        for idx, row in enumerate(assignable):
            user = row['user']
            profile = MemberProfile.objects.filter(user=user, gym=gym).first()
            fitness_goal = getattr(profile, 'fitness_goal', '') or 'GENERAL'
            goal, kcal, protein, carbs, fats = self.DIET_GOALS.get(
                fitness_goal, default_goal,
            )

            plan_specs = [(f'{goal.replace("_", " ").title()} Plan', True)]
            if idx % 4 == 0:
                plan_specs.append(('Off-Season Maintenance Plan', False))

            active_plan = None
            for name, is_active in plan_specs:
                plan, created = DietPlan.objects.get_or_create(
                    gym=gym, member=user, name=name,
                    defaults={
                        'branch': branch,
                        'created_by': (
                            owner if idx % 2 == 0
                            else trainers[idx % len(trainers)]
                        ),
                        'goal': goal if is_active else 'MAINTENANCE',
                        'daily_calories': kcal,
                        'protein_g': protein,
                        'carbs_g': carbs,
                        'fats_g': fats,
                        'is_active': is_active,
                        'start_date': today - timedelta(days=20 + idx * 2),
                        'notes': 'Seeded demo diet plan.',
                    },
                )
                self._tally('diet_plans', created)
                if is_active:
                    active_plan = plan

                for meal_type, food, portion, calories, meal_time in self.DIET_MEALS:
                    meal, meal_created = Meal.objects.get_or_create(
                        diet_plan=plan, meal_type=meal_type, food_name=food,
                        defaults={
                            'portion': portion,
                            'calories': calories,
                            'time_suggestion': meal_time,
                        },
                    )
                    self._tally('meals', meal_created)

            if active_plan is None:
                continue

            # Last 7 days of intake + adherence checklists.
            for d in range(7):
                day = today - timedelta(days=d)
                if (idx + d) % 6 != 0:  # members skip an occasional log day
                    foods = self.FOOD_ROTATION[(idx + d) % len(self.FOOD_ROTATION)]
                    _, log_created = MealLog.objects.get_or_create(
                        gym=gym, member=user, date=day,
                        defaults={
                            'branch': branch,
                            'food_items': foods,
                            'notes': 'Seeded demo meal log.',
                        },
                    )
                    self._tally('meal_logs', log_created)

                completed = [
                    ['BREAKFAST'],
                    ['BREAKFAST', 'LUNCH'],
                    ['BREAKFAST', 'LUNCH', 'DINNER'],
                    ['BREAKFAST', 'LUNCH', 'DINNER', 'EVENING_SNACK'],
                ][(idx + d) % 4]
                _, check_created = MealChecklist.objects.get_or_create(
                    member=user, date=day,
                    defaults={
                        'completed_meal_types': completed,
                        'total_meals': len(self.DIET_MEALS),
                    },
                )
                self._tally('meal_checklists', check_created)

    # ─── entry point ──────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                'DEBUG is False — refusing to seed demo data outside development.'
            )

        self.stats = {}
        password = options['password']
        demo_password = options['demo_password']
        today = timezone.localdate()

        with transaction.atomic():
            owner = self._make_user(
                self.OWNER_EMAIL, password, role=User.Role.OWNER,
                first='Admin', last='Owner',
                phone='9810000001', is_staff=True, is_superuser=True,
            )
            gym, branch, _ = self._seed_gym(owner)
            plans = self._seed_plans(gym, branch)
            promos = self._seed_offers(gym, owner, today)
            trainers, receptionists = self._seed_staff(
                gym, branch, demo_password, today,
            )
            member_rows = self._seed_members(
                gym, branch, plans, promos, demo_password, today,
            )
            self._seed_trainer_assignments(
                gym, branch, member_rows, trainers,
            )
            self._seed_lockers(gym, branch, owner, member_rows)
            self._seed_equipment(gym, branch, owner, today)
            self._seed_payments(
                gym, branch, owner, receptionists, member_rows,
            )
            self._seed_qr_tokens(gym, branch, member_rows)
            self._seed_attendance(
                gym, branch, owner, member_rows, trainers, receptionists, today,
            )
            exercises = self._seed_exercises(owner)
            self._seed_workouts(
                gym, branch, owner, trainers, member_rows, exercises, today,
            )
            self._seed_progress(gym, branch, owner, member_rows, today)
            self._seed_personal_records(gym, member_rows, exercises, today)
            self._seed_diet(gym, branch, owner, trainers, member_rows, today)

        self._print_summary(options)

    def _print_summary(self, options):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            'Seed complete — demo data summary (created / already present):'
        ))
        for key, (created, existing) in self.stats.items():
            self.stdout.write(f'  {key:<24} {created:>5} / {existing}')

        trainer_emails = ', '.join(
            f'{t[0]}.{t[1]}@{self.DEMO_DOMAIN}'.lower() for t in self.TRAINERS
        )
        staff_emails = ', '.join(
            f'{r[0]}.{r[1]}@{self.DEMO_DOMAIN}'.lower()
            for r in self.RECEPTIONISTS
        )
        self.stdout.write('')
        self.stdout.write('Demo credentials:')
        self.stdout.write(
            f'  Owner/admin : {self.OWNER_EMAIL} / {options["password"]}'
        )
        self.stdout.write(f'  Trainers    : {trainer_emails} / {options["demo_password"]}')
        self.stdout.write(f'  Reception   : {staff_emails} / {options["demo_password"]}')
        self.stdout.write(
            f'  Members     : member01@{self.DEMO_DOMAIN} … '
            f'member{len(self.MEMBERS):02d}@{self.DEMO_DOMAIN} '
            f'/ {options["demo_password"]}'
        )
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(
            'Nothing was deleted; re-running this command is a safe no-op.'
        ))
