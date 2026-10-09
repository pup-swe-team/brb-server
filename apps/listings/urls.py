from django.urls import path

from .views import ListingDetailView

urlpatterns = [path("<int:pk>", ListingDetailView.as_view(), name="listing-detail")]
