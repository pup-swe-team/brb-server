from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .services import admin_remove_review


class AdminRemoveReviewView(APIView):
    authentication_classes = (JWTAuthentication, SessionAuthentication)
    permission_classes = (IsAdminUser,)

    def delete(self, request, pk: int):
        admin_remove_review(review_id=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
