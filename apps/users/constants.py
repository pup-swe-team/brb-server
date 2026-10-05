import re

# Philippine mobile number regex (e.g., 09171234567 or +639171234567)
PHILIPPINES_MOBILE_REGEX = re.compile(r"^(?:09|\+639)\d{9}$")

# Affiliations permissible for public self-registration
ALLOWED_REGISTRATION_AFFILIATIONS = ("Student", "Faculty", "Staff")
