# 🛠️ FitCore — Developer Guide

Technical documentation for developers working on the Gym Management System.

> **For end-user documentation, see [README.md](README.md)**

---

## Table of Contents

- [Architecture Deep Dive](#architecture-deep-dive)
- [Adding a New App](#adding-a-new-app)
- [Adding New Endpoints](#adding-new-endpoints)
- [Permission System](#permission-system)
- [Serializer Patterns](#serializer-patterns)
- [Social Authentication](#social-authentication)
- [Testing Guide](#testing-guide)
- [API Usage Examples](#api-usage-examples)
- [Frontend Development](#frontend-development)
- [Database Migrations](#database-migrations)
- [Code Conventions](#code-conventions)

---

## Architecture Deep Dive

### Request Lifecycle

```
Browser → Frontend (static HTML/JS)
    ↓ fetch() with JWT
DRF Router → URL Conf → View
    ↓
Permission Classes → Throttle Classes
    ↓
Serializer (validate) → Model (save)
    ↓
Response → JSON/CSV/Excel
```

### Model Relationships

```
┌─────────────────────────────────────────────────────────────┐
│                        User (accounts)                       │
│  email, first_name, last_name, role, display_id             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌── MemberProfile (1:1) ──────────────────────────────┐   │
│  │  date_of_birth, gender, fitness_goal, height, weight │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── Membership (1:N) ────────────────────────────────┐    │
│  │  plan → MembershipPlan                               │    │
│  │  status: ACTIVE | EXPIRED | FROZEN | CANCELLED       │    │
│  │  start_date, end_date, freeze_start, freeze_end      │    │
│  │  renewed_from → self (chain)                          │    │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── FreezeRequest (1:N) ─────────────────────────────┐    │
│  │  membership → Membership                             │    │
│  │  status: PENDING | APPROVED | REJECTED               │    │
│  │  freeze_start, freeze_end, reason                    │    │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── Attendance (1:N) ────────────────────────────────┐    │
│  │  date, status: PRESENT | ABSENT                      │    │
│  │  check_in, check_out, marked_by                      │    │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── Payment (1:N) ──────────────────────────────────┐     │
│  │  amount, discount, amount_paid, payment_method       │     │
│  │  status: PENDING | PAID | REFUNDED                   │     │
│  │  membership → Membership                             │     │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── WorkoutTemplate (1:N) ──────────────────────────┐     │
│  │  name, goal, difficulty, status: DRAFT→APPROVED      │     │
│  │  └── WorkoutDay (1:N)                                │     │
│  │      └── WorkoutDayExercise (1:N) → Exercise         │     │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── DietPlan (1:N) ─────────────────────────────────┐     │
│  │  name, goal, daily_calories, protein/carbs/fats      │     │
│  │  └── Meal (1:N)                                      │     │
│  │      meal_type, food_name, calories                  │     │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── ProgressEntry (1:N) ────────────────────────────┐     │
│  │  date, weight, height, body_fat, muscle_mass         │     │
│  │  chest, waist, hips, bicep, thigh                    │     │
│  │  unique_together = (member, date)                    │     │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── PersonalRecord (1:N) ──────────────────────────┐      │
│  │  exercise → Exercise, date, value, unit              │      │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### URL Routing

All API endpoints are namespaced under `/api/<app>/`:

```python
# gym_management/urls.py
path('api/auth/',        include('apps.accounts.urls')),
path('api/members/',     include('apps.members.urls')),
path('api/memberships/', include('apps.memberships.urls')),
path('api/attendance/',  include('apps.attendance.urls')),
path('api/payments/',    include('apps.payments.urls')),
path('api/staff/',       include('apps.staff.urls')),
path('api/workouts/',    include('apps.workouts.urls')),
path('api/diet/',        include('apps.diet.urls')),
path('api/progress/',    include('apps.progress.urls')),
path('api/lockers/',     include('apps.lockers.urls')),
path('api/equipment/',   include('apps.equipment.urls')),
path('api/notifications/', include('apps.notifications.urls')),
path('api/reports/',     include('apps.reports.urls')),
path('api/trainers/',    include('apps.trainers.urls')),
```

---

## Adding a New App

### 1. Create the app

```bash
python manage.py startapp my_feature apps/my_feature
```

### 2. Register in settings.py

```python
# gym_management/settings.py
LOCAL_APPS = [
    # ... existing apps ...
    'apps.my_feature',
]
```

### 3. Create models

```python
# apps/my_feature/models.py
from django.conf import settings
from django.db import models

class MyModel(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='my_models',
    )
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'my_models'
        ordering = ['-created_at']

    def __str__(self):
        return self.name
```

### 4. Create serializers

```python
# apps/my_feature/serializers.py
from rest_framework import serializers
from .models import MyModel

class MyModelSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = MyModel
        fields = ['id', 'user', 'user_name', 'name', 'created_at']
        read_only_fields = ['id', 'created_at']
```

### 5. Create views

```python
# apps/my_feature/views.py
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import MyModel
from .serializers import MyModelSerializer

class MyModelViewSet(viewsets.ModelViewSet):
    serializer_class = MyModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ('OWNER', 'STAFF'):
            return MyModel.objects.all()
        return MyModel.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
```

### 6. Create URLs

```python
# apps/my_feature/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MyModelViewSet

router = DefaultRouter()
router.register('my-models', MyModelViewSet, basename='my-model')

urlpatterns = [
    path('', include(router.urls)),
]
```

### 7. Wire up in main URLs

```python
# gym_management/urls.py
path('api/my-feature/', include('apps.my_feature.urls')),
```

### 8. Run migrations

```bash
python manage.py makemigrations my_feature
python manage.py migrate
```

---

## Adding New Endpoints

### ViewSet (Full CRUD)

```python
class MyViewSet(viewsets.ModelViewSet):
    """Provides list, create, retrieve, update, destroy."""
    serializer_class = MySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filter by role
        user = self.request.user
        if user.role in ('OWNER', 'STAFF'):
            return MyModel.objects.all()
        return MyModel.objects.filter(user=user)
```

### Function-Based View (Custom Action)

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_custom_endpoint(request):
    # Custom logic here
    return Response({'result': 'ok'})
```

### Custom Action on ViewSet

```python
from rest_framework.decorators import action

class MyViewSet(viewsets.ModelViewSet):
    # ... standard CRUD ...

    @action(detail=False, methods=['get'], url_path='my-stats')
    def my_stats(self, request):
        """GET /api/my-feature/my-models/my-stats/"""
        qs = self.get_queryset()
        return Response({
            'total': qs.count(),
            'active': qs.filter(is_active=True).count(),
        })

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """POST /api/my-feature/my-models/<id>/approve/"""
        obj = self.get_object()
        obj.status = 'APPROVED'
        obj.save(update_fields=['status'])
        return Response({'status': 'approved'})
```

---

## Permission System

### Built-in Permission Classes

```python
# apps/accounts/permissions.py

class IsOwner(HasRole)           # Only gym owners
class IsStaff(HasRole)           # Only staff
class IsTrainer(HasRole)         # Only trainers
class IsMember(HasRole)          # Only members
class IsOwnerOrStaff(HasRole)    # Owner or Staff
class IsOwnerOrStaffOrTrainer(HasRole)  # Owner, Staff, or Trainer
class IsTrainerOrMember(HasRole) # Trainer or Member
class IsAnyStaffRole(HasRole)    # Owner, Staff, or Trainer
```

### Using Permissions

```python
# In class-based views
class MyView(APIView):
    permission_classes = [IsOwnerOrStaff]

# In function-based views
@api_view(['GET'])
@permission_classes([IsOwner])
def my_view(request):
    ...

# Decorator for function-based views
from apps.accounts.permissions import role_required

@api_view(['POST'])
@role_required(User.Role.OWNER, User.Role.STAFF)
def my_view(request):
    ...
```

### Custom Permission

```python
from rest_framework.permissions import BasePermission

class IsOwnerOfObject(BasePermission):
    """Object-level: only the user who owns the object can access it."""
    message = 'You do not have permission to access this record.'

    def has_object_permission(self, request, view, obj):
        return obj.user == request.user
```

### Role Hierarchy

```
OWNER > STAFF > TRAINER > MEMBER

OWNER:  Full access to everything
STAFF:  Members, attendance, payments, memberships, freeze requests
TRAINER: Assigned members, workout/diet plans, attendance
MEMBER: Own profile, own data only
```

---

## Serializer Patterns

### Nested Creation (Parent + Children)

```python
class ParentSerializer(serializers.ModelSerializer):
    children = ChildSerializer(many=True, required=False)

    class Meta:
        model = Parent
        fields = '__all__'

    def create(self, validated_data):
        children_data = validated_data.pop('children', [])
        validated_data['created_by'] = self.context['request'].user
        parent = Parent.objects.create(**validated_data)
        for child_data in children_data:
            Child.objects.create(parent=parent, **child_data)
        return parent
```

### Hidden Field for Current User

```python
class MySerializer(serializers.ModelSerializer):
    member = serializers.HiddenField(
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        model = MyModel
        fields = '__all__'
```

### Read-Only Computed Fields

```python
class MembershipListSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Membership
        fields = '__all__'
```

### View-Switching Serializer

```python
class MyView(generics.ListCreateAPIView):
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return MyCreateSerializer
        return MyListSerializer
```---

## Social Authentication

FitCore uses [django-allauth](https://github.com/pennersr/django-allauth) with [dj-rest-auth](https://github.com/iMerica/dj-rest-auth) for Google and Facebook social login.

### Architecture

```
Browser → Frontend (login.html / signup.html)
    ↓ socialLogin('google') / socialSignup('google')
/api/auth/google/login/ (OAuth2LoginView)
    ↓ redirect to Google consent screen
Google → /api/auth/google/callback/ (OAuth2CallbackView)
    ↓ django-allauth creates SocialAccount + User
/api/auth/3rdparty/login/callback/ (allauth)
    ↓ redirect to FRONTEND_URL with JWT tokens
```

### Key Files

| File | Purpose |
|------|---------|
| `apps/accounts/adapters.py` | Custom OAuth2 adapters that force `localhost` in callback URLs (Facebook requires `localhost` for HTTP) |
| `apps/accounts/social_views.py` | Custom OAuth2LoginView / OAuth2CallbackView using the adapters |
| `gym_management/urls.py` | Wires up `/api/auth/google/login/`, `/api/auth/facebook/login/`, and `/api/auth/3rdparty/` |
| `templates/allauth/socialaccount/login.html` | Custom allauth login confirmation page |
| `templates/allauth/socialaccount/login_cancelled.html` | Custom cancelled page |
| `templates/allauth/socialaccount/login_error.html` | Custom error page |

### Custom Adapters

Facebook rejects `127.0.0.1` as a callback host over HTTP — it requires `localhost`. The custom adapters in `adapters.py` replace `127.0.0.1` with `localhost` in callback URLs:

```python
# apps/accounts/adapters.py
class CustomGoogleOAuth2Adapter(GoogleOAuth2Adapter):
    def get_callback_url(self, request, app):
        return _force_localhost(super().get_callback_url(request, app))

class CustomFacebookOAuth2Adapter(FacebookOAuth2Adapter):
    def get_callback_url(self, request, app):
        return _force_localhost(super().get_callback_url(request, app))
```

### Configuration

In `settings.py`:

```python
# Provider credentials from .env
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID', default=''),
            'secret': config('GOOGLE_CLIENT_SECRET', default=''),
        },
        'SCOPE': ['profile', 'email'],
    },
    'facebook': {
        'APP': {
            'client_id': config('FACEBOOK_APP_ID', default=''),
            'secret': config('FACEBOOK_APP_SECRET', default=''),
        },
        'SCOPE': ['email', 'public_profile'],
    },
}

# dj-rest-auth uses JWT
REST_USE_JWT = True
REST_AUTH = {
    'TOKEN_MODEL': None,
    'USE_JWT': True,
}
```

### Frontend Integration

The login and signup pages include social login buttons:

```javascript
function socialLogin(provider) {
    window.location.href = `${API_BASE}/auth/${provider}/login/`;
}
```

After successful OAuth, allauth redirects to `FRONTEND_URL` (set in `.env`).

### Setup Steps

1. **Google**: Create OAuth 2.0 credentials in [Google Cloud Console](https://console.cloud.google.com/)
   - Authorized redirect URI: `http://localhost:8000/api/auth/google/callback/`
2. **Facebook**: Create an app in [Facebook Developers](https://developers.facebook.com/)
   - Valid OAuth redirect URI: `http://localhost:8000/api/auth/facebook/callback/`
3. Add credentials to `.env`:
   ```env
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-client-secret
   FACEBOOK_APP_ID=your-app-id
   FACEBOOK_APP_SECRET=your-app-secret
   ```
4. Create a `Site` object in Django admin (allauth requires it):
   - `Site` id=1, domain=localhost:5500, name=FitCore

---

## Testing Guide

### Test Structure

```python
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

# ─── Helpers ──────────────────────────────────────────────────────

def make_user(email, role=User.Role.MEMBER, **kwargs):
    return User.objects.create_user(
        email=email, password='TestPass123!',
        first_name='Test', last_name='User',
        role=role, **kwargs
    )

def auth_headers(user):
    token = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {str(token.access_token)}'}

# ─── Test Case ───────────────────────────────────────────────────

class MyEndpointTestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

    def test_owner_can_list(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/my-endpoint/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_forbidden(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/my-endpoint/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated(self):
        r = self.client.get('/api/my-endpoint/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
```

### CSV Content Validation

```python
import csv
import io

def parse_csv(response):
    content = response.content.decode('utf-8')
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    return rows[0], rows[1:]  # headers, data_rows

class ExportTestCase(APITestCase):
    def test_csv_headers(self):
        r = self.client.get('/api/reports/export/members/')
        headers, _ = parse_csv(r)
        self.assertEqual(headers, ['ID', 'Name', 'Email', ...])

    def test_csv_data(self):
        r = self.client.get('/api/reports/export/members/')
        _, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Alice Smith')
```

### Excel Content Validation

```python
import openpyxl
import io

def parse_excel(response):
    wb = openpyxl.load_workbook(io.BytesIO(response.content))
    ws = wb.active
    all_rows = [list(row) for row in ws.iter_rows(values_only=True)]
    return all_rows[0], all_rows[1:]  # headers, data_rows

class ExcelExportTestCase(APITestCase):
    def test_excel_headers(self):
        r = self.client.get('/api/reports/export/members/?export_format=excel')
        headers, rows = parse_excel(r)
        self.assertEqual(headers[0], 'ID')
        self.assertEqual(len(rows), 1)
```

### Running Tests

```bash
# All tests
python manage.py test

# Specific app
python manage.py test apps.memberships.tests

# Specific class
python manage.py test apps.memberships.tests.FreezeRequestApproveRejectTestCase

# Specific test
python manage.py test apps.memberships.tests.FreezeRequestApproveRejectTestCase.test_owner_can_approve

# With verbosity
python manage.py test apps.diet.tests --verbosity=2

# Keep test DB (faster iteration)
python manage.py test apps.diet.tests --keepdb
```

---

## API Usage Examples

### Login & Get Profile

```bash
# Login
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "owner@gym.com", "password": "password123"}'

# Response:
# { "access": "eyJ...", "refresh": "eyJ...", "user": {...} }

# Get profile
curl http://127.0.0.1:8000/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```

### Create a Membership

```bash
curl -X POST http://127.0.0.1:8000/api/memberships/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "member": 5,
    "plan": 1,
    "status": "ACTIVE",
    "price_paid": "1000.00"
  }'
```

### Freeze a Membership

```bash
curl -X POST http://127.0.0.1:8000/api/memberships/3/freeze/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "freeze_start": "2026-09-01",
    "freeze_end": "2026-09-14",
    "freeze_reason": "Medical leave"
  }'
```

### Create a Diet Plan with Meals

```bash
curl -X POST http://127.0.0.1:8000/api/diet/diet-plans/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Weight Loss Plan",
    "member": 5,
    "goal": "WEIGHT_LOSS",
    "daily_calories": 1800,
    "protein_g": 150,
    "meals": [
      {
        "meal_type": "BREAKFAST",
        "food_name": "Oatmeal with berries",
        "calories": 350
      },
      {
        "meal_type": "LUNCH",
        "food_name": "Grilled chicken salad",
        "calories": 500
      }
    ]
  }'
```

### Social Login (Google)

```bash
# 1. User clicks Google login button in frontend
# 2. Browser redirects to:
http://127.0.0.1:8000/api/auth/google/login/

# 3. After Google consent, user is redirected to callback:
http://127.0.0.1:8000/api/auth/google/callback/

# 4. allauth processes the callback and redirects to FRONTEND_URL
#    with JWT tokens in the URL or cookie
```

### Check Available Social Providers

```bash
curl http://127.0.0.1:8000/api/auth/3rdparty/login/

# Response:
# [
#   { "name": "Google", "id": "google", "flows": ["redirect"] },
#   { "name": "Facebook", "id": "facebook", "flows": ["redirect"] }
# ]
```

### Export Memberships as Excel

```bash
curl "http://127.0.0.1:8000/api/reports/export/memberships/?export_format=excel&status=ACTIVE" \
  -H "Authorization: Bearer <token>" \
  -o memberships.xlsx
```

### Filter Progress by Member

```bash
curl "http://127.0.0.1:8000/api/progress/entries/?member=5" \
  -H "Authorization: Bearer <token>"
```

### Get Daily Diet Summary

```bash
curl "http://127.0.0.1:8000/api/diet/meal-logs/daily-summary/?date=2026-08-31" \
  -H "Authorization: Bearer <token>"

# Response:
# {
#   "member_id": 5,
#   "member_name": "Alice Smith",
#   "date": "2026-08-31",
#   "summary": {
#     "total_calories_consumed": 1850,
#     "calorie_goal": 2000,
#     "calorie_balance": -150,
#     "calorie_balance_label": "deficit",
#     "macros": { "protein_g": 120, "carbs_g": 200, "fat_g": 55 }
#   }
# }
```

---

## Frontend Development

### Page Template

Every page follows this structure:

```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page Title — FitCore</title>
    <link rel="stylesheet" href="css/theme.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons/font/bootstrap-icons.css">
    <style>/* page-specific styles */</style>
</head>
<body>
    <!-- Sidebar -->
    <aside class="sidebar">...</aside>

    <!-- Main content -->
    <main class="main-content">
        <!-- Topbar -->
        <header class="topbar">...</header>

        <!-- Page content -->
        <div class="content-wrapper">
            <h1 class="page-title">Page Title</h1>
            <!-- Cards, tables, forms go here -->
        </div>
    </main>

    <script src="js/api.js"></script>
    <script>
        // Page-specific JavaScript
        document.addEventListener('DOMContentLoaded', async () => {
            const data = await apiGet('/my-endpoint/');
            // Render data...
        });
    </script>
</body>
</html>
```

### Adding a New Page

1. Create `frontend/my-page.html`
2. Add sidebar link in the sidebar section
3. Include `css/theme.css` and `js/api.js`
4. Use `apiGet()`, `apiPost()`, etc. for API calls
5. Use CSS classes from `theme.css` for consistent styling

### Dark Mode Checklist

- [ ] Use `var(--bg-card)` for backgrounds (not hardcoded colors)
- [ ] Use `var(--text-primary)` for text (not `#000`)
- [ ] Use `var(--border-light)` for borders
- [ ] Use `var(--shadow-sm)` for shadows
- [ ] Test with toggle in the topbar

---

## Database Migrations

### Creating Migrations

```bash
# Auto-detect model changes
python manage.py makemigrations

# Create named migration
python manage.py makemigrations my_feature -m "Add new field"
```

### Applying Migrations

```bash
python manage.py migrate
```

### Common Patterns

```python
# Add a new field with a default
migrations.AddField(
    model_name='mymodel',
    name='new_field',
    field=models.CharField(max_length=100, default=''),
),

# Rename a field
migrations.RenameField(
    model_name='mymodel',
    old_name='old_name',
    new_name='new_name',
),

# Data migration
def forward(apps, schema_editor):
    MyModel = apps.get_model('my_feature', 'MyModel')
    for obj in MyModel.objects.all():
        obj.new_field = obj.old_field
        obj.save()

migrations.RunPython(forward),
```

---

## Code Conventions

### Python

- Follow PEP 8
- Use type hints where practical
- One model per class, one view per endpoint
- Docstrings for all public classes and methods
- Use `settings.AUTH_USER_MODEL` or `get_user_model()` (never import User directly)

### JavaScript

- Use `const`/`let` (never `var`)
- Async/await for API calls
- Template literals for HTML strings
- Event delegation for dynamic content

### Git

- Conventional commit messages: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`
- One logical change per commit
- Include test coverage for new features

### File Naming

- Models: `models.py` (one file per app)
- Views: `views.py` or `views/` directory for large apps
- Serializers: `serializers.py`
- Tests: `tests.py` or `tests/` directory
- URLs: `urls.py`

---

*Last updated: September 2026*
