"""
Owner-managed custom roles API.

Endpoints:
    GET  /api/gyms/roles/           — list custom roles for the active gym (Owner)
    POST /api/gyms/roles/           — create a custom role (Owner)
    GET    /api/gyms/roles/catalog/ — grouped permission catalog (any staff-side)
    PATCH  /api/gyms/roles/<id>/    — update name/description/permissions (Owner)
    DELETE /api/gyms/roles/<id>/    — deactivate a custom role (Owner)
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwner
from apps.gyms.models import CustomRole, GymMembership
from apps.gyms.role_permissions import catalog_grouped, level_for_permissions, VALID_CODES
from apps.gyms.services import record_audit


def _actor_membership(request):
    return GymMembership.objects.filter(
        gym=getattr(request, 'gym', None),
        user=request.user,
        status=GymMembership.Status.ACTIVE,
    ).first()


def _serialize_role(role):
    return {
        'id': role.id,
        'name': role.name,
        'description': role.description,
        'permissions': role.permissions or [],
        'base_role': role.base_role,
        'is_active': role.is_active,
        'member_count': role.memberships.filter(
            status=GymMembership.Status.ACTIVE,
        ).count(),
        'created_at': role.created_at,
        'updated_at': role.updated_at,
    }


class RoleCatalogView(APIView):
    """GET /api/gyms/roles/catalog/ — permission catalog for building the UI."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'catalog': catalog_grouped(),
            'base_levels': ['STAFF', 'TRAINER', 'MEMBER'],
            'note': (
                'Granting owner-scope permissions (reports, import, trash, audit, '
                'impersonate) does NOT confer the OWNER base level; those endpoints '
                'check the individual permission.'
            ),
        })


class CustomRoleListCreateView(APIView):
    permission_classes = [IsOwner]

    def get(self, request):
        gym = getattr(request, 'gym', None)
        if gym is None:
            return Response({'detail': 'An active gym membership is required.'}, status=400)
        roles = CustomRole.objects.filter(gym=gym)
        include_inactive = str(request.query_params.get('include_inactive', '')).lower() == 'true'
        if not include_inactive:
            roles = roles.filter(is_active=True)
        return Response([_serialize_role(r) for r in roles])

    def post(self, request):
        gym = getattr(request, 'gym', None)
        if gym is None:
            return Response({'detail': 'An active gym membership is required.'}, status=400)
        name = str(request.data.get('name', '')).strip()
        if not name:
            return Response({'name': 'This field is required.'}, status=400)
        permissions = request.data.get('permissions', [])
        if not isinstance(permissions, list):
            return Response({'permissions': 'Must be a list of permission codes.'}, status=400)
        invalid = [c for c in permissions if c not in VALID_CODES]
        if invalid:
            return Response({'permissions': f'Unknown permission codes: {invalid}'}, status=400)

        if CustomRole.objects.filter(gym=gym, name__iexact=name).exists():
            return Response({'name': 'A role with this name already exists.'}, status=400)

        role = CustomRole.objects.create(
            gym=gym,
            name=name,
            description=str(request.data.get('description', '')).strip(),
            permissions=permissions,
            created_by=request.user,
        )
        record_audit(
            gym=gym,
            actor=request.user,
            action='roles.created',
            request=request,
            target=role,
            metadata={'name': role.name, 'permissions': role.permissions},
        )
        return Response(_serialize_role(role), status=201)


class CustomRoleDetailView(APIView):
    permission_classes = [IsOwner]

    def _get_role(self, request, pk):
        return CustomRole.objects.filter(
            gym=getattr(request, 'gym', None), pk=pk,
        ).first()

    def get(self, request, pk):
        role = self._get_role(request, pk)
        if role is None:
            return Response({'detail': 'Role not found.'}, status=404)
        return Response(_serialize_role(role))

    def patch(self, request, pk):
        role = self._get_role(request, pk)
        if role is None:
            return Response({'detail': 'Role not found.'}, status=404)

        if 'name' in request.data:
            name = str(request.data['name']).strip()
            if not name:
                return Response({'name': 'This field cannot be blank.'}, status=400)
            if CustomRole.objects.filter(gym=role.gym, name__iexact=name).exclude(pk=role.pk).exists():
                return Response({'name': 'A role with this name already exists.'}, status=400)
            role.name = name
        if 'description' in request.data:
            role.description = str(request.data['description']).strip()
        if 'permissions' in request.data:
            permissions = request.data['permissions']
            if not isinstance(permissions, list):
                return Response({'permissions': 'Must be a list of permission codes.'}, status=400)
            invalid = [c for c in permissions if c not in VALID_CODES]
            if invalid:
                return Response({'permissions': f'Unknown permission codes: {invalid}'}, status=400)
            role.permissions = permissions
        if 'is_active' in request.data:
            role.is_active = bool(request.data['is_active'])
        role.save()
        record_audit(
            gym=role.gym,
            actor=request.user,
            action='roles.updated',
            request=request,
            target=role,
            metadata={'name': role.name, 'permissions': role.permissions},
        )
        return Response(_serialize_role(role))

    def delete(self, request, pk):
        role = self._get_role(request, pk)
        if role is None:
            return Response({'detail': 'Role not found.'}, status=404)
        in_use = role.memberships.filter(status=GymMembership.Status.ACTIVE).exists()
        if in_use:
            # Soft-deactivate instead of hard delete while members hold it.
            role.is_active = False
            role.save(update_fields=['is_active', 'updated_at'])
            record_audit(
                gym=role.gym,
                actor=request.user,
                action='roles.deactivated',
                request=request,
                target=role,
            )
            return Response({'detail': 'Role is assigned to members; deactivated instead of deleted.'})
        record_audit(
            gym=role.gym,
            actor=request.user,
            action='roles.deleted',
            request=request,
            target=None,
            metadata={'name': role.name},
        )
        role.delete()
        return Response({'detail': 'Role deleted.'})
