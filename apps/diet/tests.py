"""
Tests for the Diet app API.

Run with:
    python manage.py test apps.diet.tests

Coverage:
    - DietPlan CRUD (create, list, retrieve, update, delete)
    - DietPlan filtering (?q=, ?goal=)
    - DietPlan stats endpoint
    - DietPlan nested meal creation
    - Meal CRUD
    - MealLog CRUD (member-scoped)
    - MealLog daily summary endpoint
    - Role-based access (Owner/Staff, Trainer, Member)
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.diet.models import DietPlan, Meal, MealLog

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


def auth_headers(user):
    token = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {str(token.access_token)}'}


# ─── DietPlan CRUD ───────────────────────────────────────────────────────────

class DietPlanCreateTestCase(APITestCase):
    """POST /api/diet/diet-plans/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER,
                                 first_name='Coach', last_name='Smith')
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Jones')
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)

    def test_trainer_can_create_diet_plan(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.post('/api/diet/diet-plans/', {
            'name': 'Weight Loss Plan',
            'member': self.member.id,
            'goal': 'WEIGHT_LOSS',
            'daily_calories': 1800,
            'protein_g': 150,
            'carbs_g': 180,
            'fats_g': 50,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(DietPlan.objects.count(), 1)
        plan = DietPlan.objects.first()
        self.assertEqual(plan.created_by, self.trainer)
        self.assertEqual(plan.member, self.member)

    def test_owner_can_create_diet_plan(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post('/api/diet/diet-plans/', {
            'name': 'Bulk Plan',
            'member': self.member.id,
            'goal': 'MUSCLE_GAIN',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_staff_can_create_diet_plan(self):
        self.client.credentials(**auth_headers(self.staff))
        r = self.client.post('/api/diet/diet-plans/', {
            'name': 'Staff Created Plan',
            'member': self.member.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_create_diet_plan(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/diet/diet-plans/', {
            'name': 'Self Plan',
            'member': self.member.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_plan_with_nested_meals(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.post('/api/diet/diet-plans/', {
            'name': 'Full Day Plan',
            'member': self.member.id,
            'goal': 'MAINTENANCE',
            'daily_calories': 2200,
            'meals': [
                {
                    'meal_type': 'BREAKFAST',
                    'food_name': 'Oatmeal with berries',
                    'portion': '1 bowl',
                    'calories': 350,
                },
                {
                    'meal_type': 'LUNCH',
                    'food_name': 'Chicken breast with rice',
                    'portion': '200g',
                    'calories': 500,
                },
            ],
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        plan = DietPlan.objects.get(name='Full Day Plan')
        self.assertEqual(plan.meals.count(), 2)
        breakfast = plan.meals.get(meal_type='BREAKFAST')
        self.assertEqual(breakfast.food_name, 'Oatmeal with berries')

    def test_unauthenticated_cannot_create_plan(self):
        r = self.client.post('/api/diet/diet-plans/', {
            'name': 'Unauth Plan',
            'member': self.member.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class DietPlanListTestCase(APITestCase):
    """GET /api/diet/diet-plans/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.other_trainer = make_user('trainer2@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)

        self.plan1 = DietPlan.objects.create(
            name='Weight Loss Plan', member=self.member,
            created_by=self.trainer, goal='WEIGHT_LOSS', is_active=True,
        )
        self.plan2 = DietPlan.objects.create(
            name='Muscle Gain Plan', member=self.other_member,
            created_by=self.other_trainer, goal='MUSCLE_GAIN', is_active=True,
        )
        self.plan3 = DietPlan.objects.create(
            name='Old Inactive Plan', member=self.member,
            created_by=self.trainer, is_active=False,
        )

    def test_owner_sees_all_plans(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/diet/diet-plans/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 3)

    def test_trainer_sees_only_own_created_plans(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.get('/api/diet/diet-plans/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        plan_ids = [p['id'] for p in results]
        self.assertIn(self.plan1.id, plan_ids)
        self.assertIn(self.plan3.id, plan_ids)
        self.assertNotIn(self.plan2.id, plan_ids)

    def test_member_sees_only_own_plans(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/diet/diet-plans/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        plan_ids = [p['id'] for p in results]
        self.assertIn(self.plan1.id, plan_ids)
        self.assertIn(self.plan3.id, plan_ids)
        self.assertNotIn(self.plan2.id, plan_ids)


class DietPlanFilterTestCase(APITestCase):
    """Filtering by ?q= and ?goal="""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Smith')

        DietPlan.objects.create(
            name='Fat Loss 101', member=self.member,
            created_by=self.owner, goal='WEIGHT_LOSS',
        )
        DietPlan.objects.create(
            name='Hypertrophy Block', member=self.member,
            created_by=self.owner, goal='MUSCLE_GAIN',
        )
        DietPlan.objects.create(
            name='Endurance Base', member=self.member,
            created_by=self.owner, goal='ENDURANCE',
        )

    def test_filter_by_goal(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/diet/diet-plans/?goal=WEIGHT_LOSS')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['goal'], 'WEIGHT_LOSS')

    def test_filter_by_q_name(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/diet/diet-plans/?q=Hyper')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertIn('Hypertrophy', results[0]['name'])

    def test_filter_by_q_member_name(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/diet/diet-plans/?q=Alice')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 3)


class DietPlanStatsTestCase(APITestCase):
    """GET /api/diet/diet-plans/stats/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

        DietPlan.objects.create(
            name='Plan A', member=self.member,
            created_by=self.owner, goal='WEIGHT_LOSS', is_active=True,
        )
        DietPlan.objects.create(
            name='Plan B', member=self.member,
            created_by=self.owner, goal='MUSCLE_GAIN', is_active=True,
        )
        DietPlan.objects.create(
            name='Plan C', member=self.member,
            created_by=self.owner, goal='WEIGHT_LOSS', is_active=False,
        )

    def test_stats_endpoint(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/diet/diet-plans/stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['total'], 3)
        self.assertEqual(r.data['active'], 2)
        self.assertEqual(r.data['weightLoss'], 2)
        self.assertEqual(r.data['muscleGain'], 1)


class DietPlanRetrieveTestCase(APITestCase):
    """GET /api/diet/diet-plans/<id>/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = DietPlan.objects.create(
            name='Test Plan', member=self.member,
            created_by=self.owner, goal='MAINTENANCE',
        )

    def test_retrieve_includes_disclaimer(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(f'/api/diet/diet-plans/{self.plan.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('disclaimer', r.data)
        self.assertIn('medical advice', r.data['disclaimer'])


class DietPlanUpdateTestCase(APITestCase):
    """PATCH /api/diet/diet-plans/<id>/"""

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = DietPlan.objects.create(
            name='Original Plan', member=self.member,
            created_by=self.trainer, goal='MAINTENANCE',
        )

    def test_trainer_can_update_own_plan(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.patch(f'/api/diet/diet-plans/{self.plan.id}/', {
            'name': 'Updated Plan',
            'daily_calories': 2000,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.name, 'Updated Plan')
        self.assertEqual(self.plan.daily_calories, 2000)

    def test_update_plan_replaces_meals(self):
        Meal.objects.create(
            diet_plan=self.plan, meal_type='BREAKFAST',
            food_name='Old Breakfast', calories=300,
        )
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.put(f'/api/diet/diet-plans/{self.plan.id}/', {
            'name': 'Updated Plan',
            'member': self.member.id,
            'meals': [
                {
                    'meal_type': 'LUNCH',
                    'food_name': 'New Lunch',
                    'calories': 600,
                },
            ],
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(self.plan.meals.count(), 1)
        self.assertEqual(self.plan.meals.first().food_name, 'New Lunch')


class DietPlanDeleteTestCase(APITestCase):
    """DELETE /api/diet/diet-plans/<id>/"""

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = DietPlan.objects.create(
            name='To Delete', member=self.member,
            created_by=self.trainer,
        )

    def test_trainer_can_delete_own_plan(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.delete(f'/api/diet/diet-plans/{self.plan.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DietPlan.objects.filter(id=self.plan.id).exists())


# ─── Meal CRUD ───────────────────────────────────────────────────────────────

class MealCRUDTestCase(APITestCase):
    """Meal CRUD via /api/diet/meals/"""

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = DietPlan.objects.create(
            name='Test Plan', member=self.member, created_by=self.trainer,
        )
        self.meal = Meal.objects.create(
            diet_plan=self.plan, meal_type='BREAKFAST',
            food_name='Oatmeal', calories=350, portion='1 bowl',
        )

    def test_trainer_can_create_meal(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.post('/api/diet/meals/', {
            'diet_plan': self.plan.id,
            'meal_type': 'LUNCH',
            'food_name': 'Chicken Salad',
            'calories': 450,
            'portion': '1 plate',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Meal.objects.count(), 2)

    def test_list_meals_filtered_by_diet_plan(self):
        Meal.objects.create(
            diet_plan=self.plan, meal_type='LUNCH',
            food_name='Rice Bowl', calories=500,
        )
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.get(f'/api/diet/meals/?diet_plan={self.plan.id}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_trainer_can_update_meal(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.patch(f'/api/diet/meals/{self.meal.id}/', {
            'food_name': 'Greek Oatmeal',
            'calories': 400,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.meal.refresh_from_db()
        self.assertEqual(self.meal.food_name, 'Greek Oatmeal')

    def test_trainer_can_delete_meal(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.delete(f'/api/diet/meals/{self.meal.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Meal.objects.filter(id=self.meal.id).exists())


# ─── MealLog CRUD ────────────────────────────────────────────────────────────

class MealLogCRUDTestCase(APITestCase):
    """MealLog CRUD via /api/diet/meal-logs/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Jones')
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)

    def test_member_can_create_meal_log(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/diet/meal-logs/', {
            'date': date.today().isoformat(),
            'food_items': [
                {'name': 'Rice', 'amount': '150g', 'calories': 200},
                {'name': 'Dal', 'amount': '100g', 'calories': 150},
            ],
            'notes': 'Lunch',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        log = MealLog.objects.first()
        self.assertEqual(log.member, self.member)
        self.assertEqual(log.total_calories, 350)

    def test_member_sees_only_own_logs(self):
        MealLog.objects.create(
            member=self.member, date=date.today(),
            food_items=[{'name': 'A', 'calories': 100}],
        )
        MealLog.objects.create(
            member=self.other_member, date=date.today(),
            food_items=[{'name': 'B', 'calories': 200}],
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/diet/meal-logs/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)

    def test_owner_sees_all_logs(self):
        MealLog.objects.create(
            member=self.member, date=date.today(),
            food_items=[{'name': 'A', 'calories': 100}],
        )
        MealLog.objects.create(
            member=self.other_member, date=date.today(),
            food_items=[{'name': 'B', 'calories': 200}],
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/diet/meal-logs/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_total_calories_auto_calculated(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/diet/meal-logs/', {
            'date': date.today().isoformat(),
            'food_items': [
                {'name': 'Eggs', 'calories': 140},
                {'name': 'Toast', 'calories': 100},
                {'name': 'Juice', 'calories': 110},
            ],
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        log = MealLog.objects.first()
        self.assertEqual(log.total_calories, 350)

    def test_filter_logs_by_date(self):
        yesterday = date.today() - timedelta(days=1)
        MealLog.objects.create(
            member=self.member, date=yesterday,
            food_items=[{'name': 'A', 'calories': 100}],
        )
        MealLog.objects.create(
            member=self.member, date=date.today(),
            food_items=[{'name': 'B', 'calories': 200}],
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get(f'/api/diet/meal-logs/?date={date.today().isoformat()}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)

    def test_delete_meal_log(self):
        log = MealLog.objects.create(
            member=self.member, date=date.today(),
            food_items=[{'name': 'A', 'calories': 100}],
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.delete(f'/api/diet/meal-logs/{log.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)


# ─── Daily Summary ───────────────────────────────────────────────────────────

class MealLogDailySummaryTestCase(APITestCase):
    """GET /api/diet/meal-logs/daily-summary/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)

        self.plan = DietPlan.objects.create(
            name='Active Plan', member=self.member,
            created_by=self.owner, goal='MAINTENANCE',
            daily_calories=2000, protein_g=150, carbs_g=200, fats_g=60,
            is_active=True, start_date=date.today(),
        )

    def test_member_gets_own_summary(self):
        MealLog.objects.create(
            member=self.member, date=date.today(),
            food_items=[
                {'name': 'Rice', 'calories': 300, 'protein': 6, 'carbs': 65, 'fat': 1},
                {'name': 'Chicken', 'calories': 250, 'protein': 35, 'carbs': 0, 'fat': 10},
            ],
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/diet/meal-logs/daily-summary/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['summary']['total_calories_consumed'], 550)
        self.assertEqual(r.data['summary']['calorie_goal'], 2000)
        self.assertIn('calorie_balance', r.data['summary'])
        self.assertEqual(r.data['summary']['calorie_balance'], -1450)
        self.assertEqual(r.data['summary']['calorie_balance_label'], 'deficit')
        self.assertIsNotNone(r.data['active_plan'])

    def test_summary_with_custom_date(self):
        yesterday = date.today() - timedelta(days=1)
        MealLog.objects.create(
            member=self.member, date=yesterday,
            food_items=[{'name': 'Pasta', 'calories': 500}],
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get(f'/api/diet/meal-logs/daily-summary/?date={yesterday.isoformat()}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['summary']['total_calories_consumed'], 500)

    def test_summary_no_logs_returns_zero(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/diet/meal-logs/daily-summary/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['summary']['total_calories_consumed'], 0)
        self.assertEqual(r.data['summary']['calorie_balance'], -2000)
        self.assertEqual(r.data['summary']['calorie_balance_label'], 'deficit')

    def test_summary_no_plan_shows_null_goal(self):
        member_no_plan = make_user('noplan@gym.com', role=User.Role.MEMBER)
        MealLog.objects.create(
            member=member_no_plan, date=date.today(),
            food_items=[{'name': 'Snack', 'calories': 200}],
        )
        self.client.credentials(**auth_headers(member_no_plan))
        r = self.client.get('/api/diet/meal-logs/daily-summary/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsNone(r.data['summary']['calorie_goal'])
        self.assertIsNone(r.data['summary']['calorie_balance'])
        self.assertEqual(r.data['summary']['calorie_balance_label'], 'on track')

    def test_owner_can_view_member_summary(self):
        MealLog.objects.create(
            member=self.member, date=date.today(),
            food_items=[{'name': 'A', 'calories': 400}],
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(f'/api/diet/meal-logs/daily-summary/?member={self.member.id}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['member_id'], self.member.id)

    def test_owner_without_member_param_returns_400(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/diet/meal-logs/daily-summary/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_summary_includes_macros(self):
        MealLog.objects.create(
            member=self.member, date=date.today(),
            food_items=[
                {'name': 'Fish', 'calories': 300, 'protein': 40, 'carbs': 5, 'fat': 15},
            ],
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/diet/meal-logs/daily-summary/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        macros = r.data['summary']['macros']
        self.assertEqual(macros['protein_g'], 40)
        self.assertEqual(macros['carbs_g'], 5)
        self.assertEqual(macros['fat_g'], 15)
        self.assertEqual(macros['protein_goal_g'], 150)

    def test_summary_includes_disclaimer(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/diet/meal-logs/daily-summary/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('disclaimer', r.data)
