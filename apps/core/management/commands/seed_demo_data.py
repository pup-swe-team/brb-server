"""Seed the catalogue the app needs before any Lender can publish.

The listing tables ship empty on purpose: an administrator fills the
categories and the pickup locations in (CP-1105/CP-1108) and a Lender
publishes against them. Until that happens `listing_statuses` and
`listing_categories` are empty, so nothing can be created and nothing can be
searched.

This command fills those two lookup tables with sane defaults and, with
`--demo`, adds demo lenders and the items they lend, so the browse and search
screens have something to show.

It is idempotent: running it twice changes nothing. `--reset` removes the demo
rows first; only rows this command created are matched, so the team's real
accounts are never touched.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.listings.constants import (
    LISTING_STATUS_ACTIVE,
    LISTING_STATUS_DEACTIVATED,
    LISTING_STATUS_DELETED,
)
from apps.listings.models import (
    AvailabilityWindow,
    Listing,
    ListingCategory,
    ListingStatus,
    PickupLocation,
)
from apps.users.models import (
    IdentityDocument,
    IdentityDocumentStatus,
    IdentityDocumentType,
    User,
)

DEMO_EMAIL_TEMPLATE = "demo.lender{index:02d}@iskolarngbayan.pup.edu.ph"
DEMO_EMAIL_PREFIX = "demo.lender"
DEFAULT_DEMO_PASSWORD = "DemoLender123!"

# A 1x1 PNG. CP-107 (encryption at rest) is not applied, so the bytes are
# stored as they are; nothing reads them but the verification review page.
TINY_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)

LISTING_STATUSES = (
    LISTING_STATUS_ACTIVE,
    LISTING_STATUS_DEACTIVATED,
    LISTING_STATUS_DELETED,
)

CATEGORIES = (
    ("Textbooks", "Course textbooks and reference books"),
    ("Reviewers", "Exam reviewers and reviewer kits"),
    ("Calculators", "Scientific and graphing calculators"),
    ("Lab Equipment", "Laboratory apparatus and course gear"),
    ("Computing", "Laptops, peripherals and accessories"),
    ("Drawing Sets", "Technical drawing instruments"),
    ("Musical Instruments", "Instruments for the music courses"),
    ("School Supplies", "Uniforms, paper and writing gear"),
)

DEMO_LENDERS = (
    ("Maria Santos", "09171234501"),
    ("Jose Ramirez", "09171234502"),
    ("Andrea Dela Cruz", "09171234503"),
    ("Miguel Bautista", "09171234504"),
    ("Princess Lim", "09171234505"),
    ("Rafael Torres", "09171234506"),
    ("Camille Aquino", "09171234507"),
    ("Diego Navarro", "09171234508"),
    ("Kristine Mercado", "09171234509"),
    ("Paolo Garcia", "09171234510"),
    ("Nicole Villanueva", "09171234511"),
    ("Angel Sy", "09171234512"),
)

# (category, title, description, condition, rate per day)
ITEM_TEMPLATES = (
    (
        "Textbooks",
        "Calculus: Early Transcendentals (Stewart)",
        (
            "8th edition, hardcover. Light highlighting on the first three chapters, "
            "pages otherwise clean. No loose or missing pages."
        ),
        "Like New",
        "35.00",
    ),
    (
        "Textbooks",
        "Fundamentals of Physics Volume 1",
        (
            "University Physics for the engineering track. Cover has a folded corner, "
            "the binding is solid. Good for review."
        ),
        "Good",
        "30.00",
    ),
    (
        "Textbooks",
        "Data Structures and Algorithms in Java",
        (
            "Course textbook used in CS 121. Some pencil notes in the margins, "
            "all answers present."
        ),
        "Fair",
        "25.00",
    ),
    (
        "Reviewers",
        "Calculus 3 Reviewer (Academic Press)",
        (
            "Complete reviewer with the 2025 edition layout. One loose page at the "
            "back, everything else intact."
        ),
        "Good",
        "20.00",
    ),
    (
        "Reviewers",
        "General Chemistry Reviewer Bundle",
        (
            "Bundle of three reviewers covering stoichiometry, equilibrium and "
            "thermodynamics. Highlighter used on two chapters."
        ),
        "Like New",
        "45.00",
    ),
    (
        "Reviewers",
        "Statistics Board Exam Reviewer",
        "Printed reviewer for the statistics board exam. Clean, no markings.",
        "Brand New",
        None,
    ),
    (
        "Calculators",
        "Casio fx-991ES Plus Scientific Calculator",
        (
            "The model our course uses. Solar plus battery, keys all working, "
            "comes with the original case."
        ),
        "Like New",
        "45.00",
    ),
    (
        "Calculators",
        "Texas Instruments TI-84 Plus CE Graphing Calculator",
        (
            "Graphing calculator for the math track. Screen has no scratches, "
            "charging cable included."
        ),
        "Good",
        "90.00",
    ),
    (
        "Calculators",
        "Casio fx-991M Scientific Calculator",
        "Budget scientific calculator. Works perfectly, new battery fitted.",
        "Good",
        "15.00",
    ),
    (
        "Lab Equipment",
        "Digital Multimeter (Fluke 115)",
        (
            "Handheld multimeter for the lab courses. Comes with test leads and "
            "the original pouch."
        ),
        "Like New",
        "55.00",
    ),
    (
        "Lab Equipment",
        "Compound Microscope with Slide Kit",
        (
            "School-grade microscope for the biology track. Slides and the slide "
            "preparation kit included."
        ),
        "Good",
        "40.00",
    ),
    (
        "Lab Equipment",
        "Lab Coat and Safety Goggles Set",
        "Clean lab coat (size M) and goggles, washed after the last lab class.",
        "Good",
        None,
    ),
    (
        "Computing",
        "Lenovo IdeaPad Slim 3 (8GB / 256GB)",
        (
            "Laptop for write-ups and coding subjects. Battery holds about four "
            "hours, charger included."
        ),
        "Fair",
        "120.00",
    ),
    (
        "Computing",
        "Logitech MK270 Wireless Keyboard and Mouse Set",
        "Wireless combo set, still paired to its USB receiver. Keys are clean.",
        "Like New",
        "25.00",
    ),
    (
        "Computing",
        "Arduino Uno R3 Starter Kit",
        (
            "Board, breadboard, jumper wires and sensors in the original case. "
            "Everything works."
        ),
        "Like New",
        "35.00",
    ),
    (
        "Drawing Sets",
        "A3 Drawing Kit with Compass and Scale",
        (
            "Complete engineering drawing kit: triangles, protractor, compass, "
            "scales and a pencil case."
        ),
        "Good",
        "30.00",
    ),
    (
        "Drawing Sets",
        "Architect's Scale Set (6 Scales)",
        "Set of six triangular scales in a soft pouch.",
        "Brand New",
        None,
    ),
    (
        "Musical Instruments",
        "Yamaha Acoustic Guitar F310",
        (
            "Classical guitar for the music track. New strings fitted, includes "
            "the gig bag and a clip-on tuner."
        ),
        "Good",
        "80.00",
    ),
    (
        "Musical Instruments",
        "Digital Metronome and Tuner",
        "Clip-on tuner and metronome, both work perfectly.",
        "Like New",
        "15.00",
    ),
    (
        "School Supplies",
        "PE Uniform Set (Shirt and Shorts)",
        "Washed and ready to wear, size M. Shirt still has the school logo.",
        "Good",
        None,
    ),
    (
        "School Supplies",
        "Whiteboard Marker Set (12 Colors)",
        "New set of 12 markers, no dried tips.",
        "Brand New",
        None,
    ),
    (
        "School Supplies",
        "Arch Lever File and Notebook Bundle",
        "Heavy-duty lever arch file plus three ruled notebooks, all unused.",
        "Brand New",
        None,
    ),
    (
        "Textbooks",
        "Engineering Economy by Blank and Tarquin",
        (
            "Standard reference for the engineering economy course. Spine is "
            "cracked but every page is there."
        ),
        "Fair",
        "40.00",
    ),
    (
        "Reviewers",
        "Organic Chemistry Reviewer (2024 Edition)",
        "Reactions and mechanisms reviewer. One bookmark left inside.",
        "Good",
        "25.00",
    ),
    (
        "Calculators",
        "Scientific Calculator (Casio fx-570)",
        "Four-function scientific calculator for basic courses. Works fine.",
        "Fair",
        "10.00",
    ),
    (
        "Lab Equipment",
        "Science Calculator and Periodic Table Kit",
        (
            "The science kit from the grade 11 lab: a scientific calculator and a "
            "printable periodic table."
        ),
        "Good",
        None,
    ),
    (
        "Computing",
        "HDMI Cable 2m and USB-C Adapter",
        "Spare adapters for the media lab machines.",
        "Brand New",
        None,
    ),
    (
        "Drawing Sets",
        "Staedtler Lumocolor Pen Set (12)",
        "Fineliners in a pouch, used for about half the set.",
        "Good",
        "12.00",
    ),
    (
        "Musical Instruments",
        "Keyboard Stand (X-Stand)",
        "Folding stand for a 61-key keyboard.",
        "Good",
        "35.00",
    ),
    (
        "Textbooks",
        "Operations Research by Taha",
        "Hardcover edition for the quantitative methods course.",
        "Like New",
        "50.00",
    ),
)


class Command(BaseCommand):
    help = (
        "Fill the empty listing lookup tables and optionally add demo lenders "
        "and the items they lend."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo",
            action="store_true",
            help="Also create demo lenders and their listings.",
        )
        parser.add_argument(
            "--lenders",
            type=int,
            default=12,
            help="How many demo lenders to create (default: 12).",
        )
        parser.add_argument(
            "--items",
            type=int,
            default=30,
            help="How many demo items to spread across the lenders (default: 30).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the demo rows (only the ones this command created) first.",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_DEMO_PASSWORD,
            help=f"Password for the demo lenders (default: {DEFAULT_DEMO_PASSWORD}).",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            statuses = self._seed_listing_statuses()
            categories = self._seed_categories()
            locations = self._seed_pickup_locations()

            demo_summary = {}
            if options["reset"]:
                demo_summary["removed"] = self._remove_demo_rows()
            if options["demo"]:
                demo_summary.update(
                    self._seed_demo_lenders(
                        lenders=options["lenders"],
                        items=options["items"],
                        password=options["password"],
                        categories=categories,
                        statuses=statuses,
                        locations=locations,
                    )
                )

        self.stdout.write(self.style.SUCCESS("Seed complete."))
        self.stdout.write(f"  listing statuses : {', '.join(sorted(statuses))}")
        self.stdout.write(f"  listing categories: {len(categories)}")
        if demo_summary:
            for key, value in demo_summary.items():
                self.stdout.write(f"  {key:17s}: {value}")
        if options["demo"]:
            self.stdout.write("")
            self.stdout.write(
                f"  demo login: {DEMO_EMAIL_TEMPLATE.format(index=1)} "
                f"/ {options['password']}"
            )

    # -- lookup tables -------------------------------------------------

    def _seed_listing_statuses(self) -> dict[str, ListingStatus]:
        statuses = {}
        for name in LISTING_STATUSES:
            status, _ = ListingStatus.objects.get_or_create(name=name)
            statuses[name] = status
        return statuses

    def _seed_categories(self) -> dict[str, ListingCategory]:
        categories = {}
        for name, description in CATEGORIES:
            category, _ = ListingCategory.objects.get_or_create(
                name=name, defaults={"description": description}
            )
            categories[name] = category
        return categories

    def _seed_pickup_locations(self) -> list[PickupLocation]:
        locations = list(
            PickupLocation.objects.filter(deleted_at__isnull=True).order_by("name")
        )
        if not locations:
            locations = [
                PickupLocation.objects.create(
                    name="Main Campus Library",
                    description="Seeded by seed_demo_data; rename it in the portal.",
                )
            ]
        return locations

    # -- demo data -----------------------------------------------------

    def _remove_demo_rows(self) -> int:
        """Delete the demo lenders this command created, and only those."""
        demo_users = User.objects.filter(email__startswith=DEMO_EMAIL_PREFIX)
        count = demo_users.count()
        # The listings, availability windows and identity documents hang off the
        # user, so the cascade takes them with it.
        demo_users.delete()
        return count

    def _seed_demo_lenders(
        self,
        *,
        lenders: int,
        items: int,
        password: str,
        categories: dict[str, ListingCategory],
        statuses: dict[str, ListingStatus],
        locations: list[PickupLocation],
    ) -> dict[str, int]:
        rng = random.Random(20261022)
        names = DEMO_LENDERS
        lenders = min(lenders, len(names))
        # Spread the items evenly: 30 items over 12 lenders is six lenders with
        # three and six with two, not ten lenders with three and two with none.
        base, remainder = divmod(items, lenders) if lenders else (0, 0)
        shares = [base + (1 if index < remainder else 0) for index in range(lenders)]

        created_lenders = 0
        created_items = 0
        skipped = 0
        template_index = 0

        for offset in range(lenders):
            full_name, contact_number = names[offset]
            email = DEMO_EMAIL_TEMPLATE.format(index=offset + 1)
            lender = User.objects.filter(email=email).first()
            if lender is None:
                lender = self._create_lender(
                    email=email,
                    full_name=full_name,
                    contact_number=contact_number,
                    password=password,
                )
                created_lenders += 1
            elif lender.listings.exists():
                # Already seeded: leave the existing catalogue alone, but keep
                # the password in step with what the command reports.
                if not lender.check_password(password):
                    lender.set_password(password)
                    lender.save(update_fields=["password"])
                skipped += 1
                continue

            for _ in range(shares[offset]):
                if template_index >= len(ITEM_TEMPLATES):
                    break
                template = ITEM_TEMPLATES[template_index]
                created_items += self._create_listing(
                    lender=lender,
                    template=template,
                    categories=categories,
                    statuses=statuses,
                    # Round-robin over the pickup locations, so the location
                    # filter in the app has more than one value to filter on.
                    location=locations[template_index % len(locations)],
                    rng=rng,
                )
                template_index += 1

        return {
            "demo lenders": created_lenders,
            "demo items": created_items,
            "lenders skipped": skipped,
        }

    def _create_lender(
        self, *, email: str, full_name: str, contact_number: str, password: str
    ) -> User:
        lender = User.objects.create_user(
            email=email,
            password=password,
            full_name=full_name,
            contact_number=contact_number,
            affiliation=User.AffiliationChoices.STUDENT,
            account_status=User.AccountStatusChoices.ACTIVE,
            lender_status=User.LenderStatusChoices.ACTIVE,
        )
        lender.email_verified_at = timezone.now()
        lender.save(update_fields=["email_verified_at"])

        # CP-105: publishing is gated on an approved identity document, so the
        # demo lenders get one and can publish for real.
        document_type, _ = IdentityDocumentType.objects.get_or_create(name="pup_id")
        approved, _ = IdentityDocumentStatus.objects.get_or_create(name="approved")
        reviewer = User.objects.filter(is_staff=True).order_by("pk").first()
        IdentityDocument.objects.create(
            user=lender,
            document_type=document_type,
            id_number=f"DEMO-{lender.pk:05d}",
            document_data=TINY_PNG_BYTES,
            status=approved,
            name_on_document=full_name,
            has_profile_mismatch=False,
            consent_given=True,
            consented_at=timezone.now(),
            reviewed_by=reviewer,
            reviewed_at=timezone.now(),
        )
        return lender

    def _create_listing(
        self,
        *,
        lender: User,
        template: tuple,
        categories: dict[str, ListingCategory],
        statuses: dict[str, ListingStatus],
        location: PickupLocation,
        rng: random.Random,
    ) -> int:
        category_name, title, description, condition, rate = template
        rate_per_day = Decimal(rate) if rate is not None else None
        listing = Listing.objects.create(
            lender=lender,
            title=title,
            description=description,
            category=categories[category_name],
            condition=condition,
            pickup_location=location,
            rate_per_day=rate_per_day,
            is_ownership_confirmed=True,
            status=statuses[LISTING_STATUS_ACTIVE],
        )
        today = timezone.localdate()
        AvailabilityWindow.objects.create(
            listing=listing,
            start_date=today - timedelta(days=7),
            end_date=today + timedelta(days=60 + rng.randint(0, 30)),
        )
        return 1
