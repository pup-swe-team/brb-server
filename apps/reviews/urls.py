"""URL routing for mutual reviews and ratings (CP-601)."""

from django.urls import path

from .views import (
    OrderReviewListCreateView,
    OrderUserReviewDetailView,
    ReviewCreateView,
    ReviewDetailView,
    UserReviewListView,
)

urlpatterns = [
    path(
        "orders/<int:order_id>/reviews/",
        OrderReviewListCreateView.as_view(),
        name="order-reviews",
    ),
    path(
        "orders/<int:order_id>/review/",
        OrderUserReviewDetailView.as_view(),
        name="order-user-review",
    ),
    path(
        "reviews/",
        ReviewCreateView.as_view(),
        name="review-create",
    ),
    path(
        "reviews/<int:pk>/",
        ReviewDetailView.as_view(),
        name="review-detail",
    ),
    path(
        "users/<int:user_id>/reviews/",
        UserReviewListView.as_view(),
        name="user-reviews",
    ),
]
