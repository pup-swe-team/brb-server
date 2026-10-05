from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import UserRegistrationSerializer, UserResponseSerializer
from .services import register_user


class RegisterView(APIView):
    """
    Endpoint for public user registration with PUP-affiliated email (CP-101).
    POST /api/v1/auth/register/
    """

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = register_user(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            full_name=serializer.validated_data["full_name"],
            contact_number=serializer.validated_data["contact_number"],
            affiliation=serializer.validated_data["affiliation"],
        )

        response_data = {
            "message": "Registration successful. Your account is pending verification.",
            "user": UserResponseSerializer(user).data,
        }
        return Response(response_data, status=status.HTTP_201_CREATED)
