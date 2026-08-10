"""Entrypoint for the web-kernel and CLI tools (imperal validate/build).
Sets up sys.path, purges stale module cache, then imports ext/chat and all
handler modules so their decorators register on the same Extension instance."""
import os
import sys

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

# Purge stale cached modules so a fresh load always registers decorators correctly
# (the validator may run multiple extensions in the same process).
_LOCAL = ("app", "handlers_connect", "handlers_read", "handlers_woocommerce",
          "handlers_woocommerce_catalog", "handlers_woocommerce_operations",
          "handlers_woocommerce_finance", "handlers_woocommerce_order_edit",
          "handlers_seo", "handlers_builders", "handlers_posts", "handlers_media",
          "handlers_taxonomy", "handlers_links", "handlers_users", "handlers_menus", "handlers_post_lifecycle", "handlers_reviews", "handlers_site_settings", "handlers_redirects", "skeleton", "panels", "models", "storage", "wp_client", "wp_cli", "gutenberg")
for _mod in _LOCAL:
    sys.modules.pop(_mod, None)

from app import ext, chat  # noqa: E402,F401
import handlers_connect  # noqa: E402,F401
import handlers_read  # noqa: E402,F401
import handlers_woocommerce  # noqa: E402,F401
import handlers_woocommerce_catalog  # noqa: E402,F401
import handlers_woocommerce_operations  # noqa: E402,F401
import handlers_woocommerce_finance  # noqa: E402,F401
import handlers_woocommerce_order_edit  # noqa: E402,F401
import handlers_seo  # noqa: E402,F401
import handlers_builders  # noqa: E402,F401
import handlers_posts  # noqa: E402,F401
import handlers_media  # noqa: E402,F401
import handlers_taxonomy  # noqa: E402,F401
import handlers_links  # noqa: E402,F401
import handlers_users  # noqa: E402,F401
import handlers_menus  # noqa: E402,F401
import handlers_post_lifecycle  # noqa: E402,F401
import handlers_reviews  # noqa: E402,F401
import handlers_site_settings  # noqa: E402,F401
import handlers_redirects  # noqa: E402,F401
import handlers_maintenance  # noqa: E402,F401
import handlers_rankmath  # noqa: E402,F401
import handlers_indexnow  # noqa: E402,F401
import skeleton  # noqa: E402,F401
import panels  # noqa: E402,F401
