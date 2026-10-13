"""Makes CAPE's apiv2 accept CAPE_API_TOKEN, and only that token, for the `tartarus` user.

Fed to `manage.py shell` by provision-api-token, so Django is set up. Idempotent; rotating
CAPE_API_TOKEN and restarting the container revokes the old token.
"""

import os

from apikey.models import ApiKey, hash_key
from django.contrib.auth.models import User

token_hash = hash_key(os.environ["CAPE_API_TOKEN"])
user, _ = User.objects.get_or_create(username="tartarus")
ApiKey.objects.filter(user=user).exclude(key=token_hash).delete()
ApiKey.objects.get_or_create(user=user, key=token_hash, defaults={"name": "tartarus-backend"})
